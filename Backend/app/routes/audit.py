from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from pydantic import BaseModel
import os
from ..services.retrieval import get_relevant_context
from semantic_router.encoders import HuggingFaceEncoder
from semantic_chunkers import StatisticalChunker
from openai import AsyncOpenAI
import docx2txt
import io
import asyncio
from typing import List, Dict
import json
from dotenv import load_dotenv

load_dotenv()

router = APIRouter()

# Define paths directly
FAISS_INDEX_PATH = "db/regulatory_index.faiss"
SQLITE_DB_PATH = "db/chunks.db"

SOP_MIN_tokens = 100
SOP_MAX_tokens = 500

# Initialize encoder and chunker
encoder = HuggingFaceEncoder(name="sentence-transformers/all-MiniLM-L6-v2")
chunker = StatisticalChunker(
    encoder=encoder,
    min_split_tokens=SOP_MIN_tokens,
    max_split_tokens=SOP_MAX_tokens,
)

# Initialize OpenAI client
client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))

class QueryRequest(BaseModel):
    query: str
    top_k: int = 5

async def get_hybrid_context(query: str, chunk: Dict, faiss_path: str, db_path: str, top_k: int) -> Dict:
    """
    Get relevant context from both vector DB and graph DB for a query + chunk combination.
    """
    # Combine query with chunk content to create a more specific search
    enhanced_query = f"{query} context: {chunk['text']}"
    
    # Get hybrid context using the enhanced query
    context = get_relevant_context(
        query=enhanced_query,
        faiss_path=faiss_path,
        db_path=db_path,
        top_k=top_k
    )
    
    # Return the results directly
    return context["results"]

async def process_chunk_with_openai(
    chunk: Dict,
    query: str,
    context_results: Dict,
    client: AsyncOpenAI
) -> Dict:
    """
    Process a single chunk with OpenAI, incorporating hybrid retrieval results.
    Returns structured analysis identifying errors with citations.
    """
    # Construct the prompt with chunk, query, and hybrid context results
    prompt = f"""
    Analyze this SOP document chunk for compliance issues by comparing it with the regulatory context.
    For each issue found, provide the following EXACT format:

    ISSUE IN SOP DOCUMENT:
    [Quote the exact text from the SOP document that contains the issue]

    WHY ERROR:
    [Explain specifically why this is a compliance issue or violation]

    CITATION FROM CONTEXT:
    [Quote the specific regulatory text that identifies this as an issue, including document name and page number]

    If no issues are found, respond with exactly: "No compliance issues found in this section."

    SOP DOCUMENT CHUNK:
    {chunk['text']}
    Source: {chunk.get('doc_name', 'Unknown')}

    REGULATORY CONTEXT:
    {json.dumps([{
        'text': r['text'],
        'source': r.get('doc_name', 'Unknown'),
        'page': r.get('page_range', 'N/A')
    } for r in context_results.get('results', [])], indent=2)}
    """
    
    try:
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are a compliance expert analyzing SOP documents against regulatory requirements. Identify issues using the exact format specified."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.1,
            max_tokens=1000
        )
        
        return {
            "chunk": chunk,
            "analysis": response.choices[0].message.content,
            "context": context_results,
            "score": chunk.get('score', 0)
        }
    except Exception as e:
        return {
            "chunk": chunk,
            "analysis": f"Error in OpenAI processing: {str(e)}",
            "context": context_results,
            "score": chunk.get('score', 0)
        }

@router.post("/search")
async def search_regulations(
    query: str = Form(...),
    top_k: int = Form(5),
    file: UploadFile = File(None)
):
    """
    Search through processed regulatory documents and optionally a new DOCX file.
    Process each chunk sequentially and return individual results.
    """
    try:
        # Verify that the necessary database files exist
        if not os.path.exists(FAISS_INDEX_PATH):
            raise HTTPException(
                status_code=400, 
                detail="No FAISS index found. Please process some PDF documents first."
            )
        if not os.path.exists(SQLITE_DB_PATH):
            raise HTTPException(
                status_code=400, 
                detail="No SQLite database found. Please process some PDF documents first."
            )
        
        # Process DOCX file if provided
        docx_chunks = []
        if file and file.filename.endswith('.docx'):
            content = await file.read()
            text = docx2txt.process(io.BytesIO(content))
            chunks = chunker(docs=[text])
            docx_chunks = [
                {
                    'text': chunk.content,
                    'doc_name': file.filename,
                    'page_range': 'N/A'
                }
                for chunk in chunks[0]
            ]
        
        # Get context for the original query
        base_context = get_relevant_context(
            query=query,
            faiss_path=FAISS_INDEX_PATH,
            db_path=SQLITE_DB_PATH,
            top_k=top_k
        )
        
        # Process chunks sequentially and collect results
        individual_results = []
        if docx_chunks:
            for chunk in docx_chunks:
                # Get hybrid context for this chunk
                chunk_context = await get_hybrid_context(
                    query=query,
                    chunk=chunk,
                    faiss_path=FAISS_INDEX_PATH,
                    db_path=SQLITE_DB_PATH,
                    top_k=top_k
                )
                
                # Process with OpenAI
                analysis = await process_chunk_with_openai(
                    chunk=chunk,
                    query=query,
                    context_results={"results": chunk_context},
                    client=client
                )
                
                # Extract and format the individual result
                individual_results.append({
                    # "document": chunk['doc_name'],
                    # "page_range": chunk['page_range'],
                    "chunk_text": chunk['text'],
                    "analysis_result": analysis['analysis']
                })
        
        return {
            "success": True,
            "query": query,
            "individual_results": individual_results,
            "storage_info": {
                "faiss_index_path": FAISS_INDEX_PATH,
                "sqlite_db_path": SQLITE_DB_PATH
            }
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
