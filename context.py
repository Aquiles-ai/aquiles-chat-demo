from openai import AsyncOpenAI
from typing import Callable, Sequence, Awaitable, Union
from aquiles.client import AsyncAquilesRAG
import json
from Artemisa.Extractor import PDFExtractor, ExcelExtractor, DocxExtractor
from pathlib import Path


client = AsyncOpenAI()

EmbeddingFunc = Callable[[str], Union[Sequence[float], Awaitable[Sequence[float]]]]

SYSTEMPROMPT = """
You are an assistant specialized in transforming user queries into optimized search queries for Retrieval-Augmented Generation (RAG) systems.  
Your task is to receive an “original_query” and output between 3 and 5 distinct queries that:

1. Include synonyms and linguistic variations of the key terms.  
2. Are concise (no more than 6–8 words each).  
3. Aim to maximize semantic coverage in retrieval.  
4. Avoid unnecessary punctuation or filler phrases.

**Output format** (strict JSON):
{
  "original_query": "<original user query>",
  "optimized_queries": [
    "<query_1>",
    "<query_2>",
    "…"
  ]
}

**Example**  
- Input:  
  “How can I train a multimodal model with ViT and an LLM?”  
- Expected output:  
  {
    "original_query": "How can I train a multimodal model with ViT and an LLM?",
    "optimized_queries": [
      "train multimodal model ViT LLM",
      "ViT LLM multimodal training guide",
      "setting up multimodal ViT LLM training",
      "multimodal ViT LLM hyperparameters",
      "examples multimodal model training ViT LLM"
    ]
  }

Make sure that most queries are in English, and a few in the language of the question.
Always return only the JSON object with the keys `original_query` and `optimized_queries`. Do not include any additional commentary.
"""

SYSTEMPROMPTLLM = """
You are an expert assistant that answers user queries based on retrieved document chunks.
Given an original user query and a list of document snippets with metadata, craft a precise and comprehensive answer.
"""


async def get_emb(text):
    response = await client.embeddings.create(
        input=text,
        model="text-embedding-3-small"
    )
    return response.data[0].embedding

class RAGPipeline:
    def __init__(self, query: str, embedding_func: EmbeddingFunc, model: str, host: str, api_key_rag: str, index_rag: str):
        self.query = query
        self.function = embedding_func
        self.client = client
        self.model = model
        self.clientrag = AsyncAquilesRAG(host=host, api_key=api_key_rag)
        self.index_rag = index_rag

    async def gen_querys(self):
        try:
            response = await self.client.responses.create(
                input=self.query,
                model=self.model,
                instructions=SYSTEMPROMPT
            )

            content = response.output_text

            data = json.loads(content)
            optimized = data.get("optimized_queries", [])
            return optimized
        except Exception as e:
            print(f"Error: {e}")
            return []

    async def get_rag(self, top_k: int = 5):
        querys = await self.gen_querys()
        all_chunks = []
        for q in querys:
            emb = await self.function(q)
            docs = await self.clientrag.query(
                self.index_rag,
                embedding=emb,
                top_k=top_k
            )
            chunks = docs.get("results", [])
            all_chunks.extend(chunks)
        return all_chunks

    async def answer(self, func, top_k: int = 5 ):
        chunks = await self.get_rag(top_k)
        chunks_sorted = sorted(chunks, key=lambda d: d.get("score", 0), reverse=True)
        top_chunks = chunks_sorted[: top_k]

        context_text = "\n---\n".join(
            f"Chunk: {c['name_chunk']} (score: {c['score']})\n{c['raw_text']}"
            for c in top_chunks
        )

        context = f"original_query: {self.query}\nretrieved_context: {context_text}"

        response = await self.client.responses.create(
            input=context,
            model=self.model,
            instructions=SYSTEMPROMPTLLM,
            stream=True
        )

        async for event in response:
            if hasattr(event, "delta"):
                await func(event.delta)

class RAGIndexer:
    def __init__(self, embedding_func: EmbeddingFunc, host: str, api_key_rag: str, index_rag: str):
        self.client = AsyncAquilesRAG(host=host, api_key=api_key_rag)
        self.embedding_func = embedding_func
        self.index_rag = index_rag

    async def indexdocs(self,
        path = None,
        type_doc = None,
        text = None,
        use_document: bool = True):

        print("Procesando el documento")

        if use_document:
            if not path or not type_doc:
                raise ValueError("Para indexar documento debes especificar path y type_doc")
            if type_doc == "pdf":
                extractor = PDFExtractor(path)
                pages = extractor.extract_all()["pages"]
                content = [p["text"] for p in pages if p.get("text")]
            elif type_doc == "excel":
                extractor = ExcelExtractor(path)
                _, df = extractor.excel()
                content = df.astype(str).agg(" ".join, axis=1).tolist()
            elif type_doc == "word":
                extractor = DocxExtractor(path)
                paras = extractor.extract_all()["paragraphs"]
                content = [p["text"] for p in paras if isinstance(p, dict) and p.get("text")]
            else:
                raise ValueError(f"Tipo de documento '{type_doc}' no soportado")
        else:
            if not text:
                raise ValueError("Para indexar texto directo debes pasar el parámetro text")
            content = [text]

        print("Indexando el documento")

        results = await self.client.send_rag(embedding_func=self.embedding_func, index=self.index_rag, name_chunk=Path(path).name if use_document else 'inline', raw_text=str(content))

        print("Documento indexado")
        return True

#test = RAGPipeline("Hey me podrias decir que efectos secundarios tiene ChatGPT en el cerebro?", get_emb, 
#        model="gpt-4.1", host="http://192.168.1.20:5500", 
#        api_key_rag="dummy-api-key", index_rag="docs2")

#async def testr():
#    async for q in test.answer():
#        print(q, end="", flush=True)

#if __name__ == "__main__":
#    import asyncio

#    asyncio.run(testr())

#async def ind():

#    indexer = RAGIndexer(get_emb, host="http://192.168.1.20:5500", 
#        api_key_rag="dummy-api-key", index_rag="docs2")

#    await indexer.indexdocs(path="2506.08872v1.pdf", type_doc="pdf")

#if __name__ == "__main__":
#    import asyncio

#    asyncio.run(ind())