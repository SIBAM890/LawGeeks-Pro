import os
from dotenv import load_dotenv
from operator import itemgetter  # <--- Added this import for safe data extraction
from langchain_google_genai import GoogleGenerativeAIEmbeddings, ChatGoogleGenerativeAI
from langchain_chroma import Chroma
from langchain.prompts import ChatPromptTemplate
from langchain.schema.output_parser import StrOutputParser

# Load environment variables
load_dotenv(dotenv_path="scripts/.env")

VECTOR_DB_DIR = "vector_db" # Path relative to where the API is run (root)

class RAGService:
    def __init__(self):
        self.api_key = os.getenv("GOOGLE_API_KEY")
        if not self.api_key:
            raise ValueError("GOOGLE_API_KEY not set.")

        # 1. Initialize Embedding Model
        self.embeddings = GoogleGenerativeAIEmbeddings(
            model="models/embedding-001",
            google_api_key=self.api_key
        )

        # 2. Load the Vector Database
        self.vectordb = Chroma(
            persist_directory=VECTOR_DB_DIR,
            embedding_function=self.embeddings
        )
        self.retriever = self.vectordb.as_retriever(search_kwargs={"k": 3}) # Retrieve top 3 chunks

        # 3. Initialize LLM
        self.llm = ChatGoogleGenerativeAI(
            model="models/gemini-pro-latest", 
            google_api_key=self.api_key,
            temperature=0.3
        )

        # 4. Define the RAG Prompt Template
        rag_prompt_template = """
        You are "LawGeeks", a specialized AI assistant. Your goal is to answer a user's specific question about their legal document, using *only* the provided context.
        
        You have been given three pieces of information:
        1.  **THE USER'S DOCUMENT**: The full text of their agreement.
        2.  **RELEVANT LEGAL CONTEXT**: Snippets from Indian law (e.g., The Contract Act, RERA) that are relevant to the user's question.
        3.  **THE USER'S QUESTION**: The specific question the user asked.

        **INSTRUCTIONS:**
        1.  First, analyze the **USER'S DOCUMENT** to find clauses that relate to the **USER'S QUESTION**.
        2.  Next, use the **RELEVANT LEGAL CONTEXT** to understand the standard legal position or definitions.
        3.  Combine these insights to provide a clear, simple, and direct answer.
        4.  If the user's document is silent on the issue, say so.
        5.  If the user's document *contradicts* the legal context, point this out (e.g., "Your document states X, which is unusual as the standard legal position is Y...").
        6.  **DO NOT** make up information. If the answer cannot be found in the provided texts, state that you cannot answer.
        7.  **DO NOT** provide legal advice. Frame your answer as "This clause appears to mean..." or "This document states...".

        ---
        **THE USER'S DOCUMENT:**
        {document_context}
        ---
        **RELEVANT LEGAL CONTEXT:**
        {rag_context}
        ---
        **THE USER'S QUESTION:**
        {question}
        ---

        **Your Answer:**
        """
        self.rag_prompt = ChatPromptTemplate.from_template(rag_prompt_template)

    def _format_docs(self, docs):
        # Helper to join retrieved docs into a single string
        return "\n\n---\n\n".join(doc.page_content for doc in docs)

    def answer_user_query(self, document_text: str, user_question: str) -> str:
        """
        Answers a user's question using the RAG pipeline.
        """
        try:
            # We use itemgetter to safely extract specific keys from the input dict
            # This prevents the "expected string, got dict" error
            rag_chain = (
                {
                    # 1. Get 'question', search DB, then format results
                    "rag_context": itemgetter("question") | self.retriever | self._format_docs,
                    # 2. Pass the 'question' straight through
                    "question": itemgetter("question"),
                    # 3. Pass the 'document_context' straight through
                    "document_context": itemgetter("document_context")
                }
                | self.rag_prompt
                | self.llm
                | StrOutputParser()
            )
            
            # Invoke the chain
            response = rag_chain.invoke({
                "question": user_question, 
                "document_context": document_text
            })
            return response
            
        except Exception as e:
            print(f"Error in RAG chain: {e}")
            return "I encountered an error trying to find the answer. Please try rephrasing your question."