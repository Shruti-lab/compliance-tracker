"""ChromaDB vector store for compliance document embeddings."""

import logging
from pathlib import Path
from typing import List, Dict, Any, Optional
import chromadb
from chromadb.config import Settings
from sentence_transformers import SentenceTransformer


class ChromaComplianceStore:
    """Manages ChromaDB vector store for compliance documents."""
    
    def __init__(
        self,
        persist_directory: str = 'src/vectorstore/chroma_data',
        embedding_model: str = 'sentence-transformers/all-MiniLM-L6-v2',
        logger: Optional[logging.Logger] = None
    ):
        """
        Initialize ChromaDB store.
        
        Args:
            persist_directory: Directory to persist ChromaDB data
            embedding_model: Sentence transformer model name
            logger: Logger instance
        """
        self.persist_directory = Path(persist_directory)
        self.persist_directory.mkdir(parents=True, exist_ok=True)
        
        self.logger = logger or logging.getLogger(__name__)
        
        # Initialize ChromaDB client
        self.client = chromadb.PersistentClient(
            path=str(self.persist_directory),
            settings=Settings(
                anonymized_telemetry=False,
                allow_reset=True
            )
        )
        
        # Initialize embedding model
        self.logger.info(f"Loading embedding model: {embedding_model}")
        self.embedding_model = SentenceTransformer(embedding_model)
        self.logger.info("Embedding model loaded successfully")
        
        # Cache for collections
        self._collections: Dict[str, chromadb.Collection] = {}
    
    def get_or_create_collection(
        self,
        framework: str,
        reset: bool = False
    ) -> chromadb.Collection:
        """
        Get or create a collection for a compliance framework.
        
        Args:
            framework: Compliance framework name (e.g., 'soc2', 'iso27001')
            reset: Whether to reset the collection if it exists
            
        Returns:
            ChromaDB collection
        """
        collection_name = f"compliance_{framework.lower()}"
        
        if reset and collection_name in self._collections:
            del self._collections[collection_name]
            try:
                self.client.delete_collection(collection_name)
                self.logger.info(f"Reset collection: {collection_name}")
            except Exception:
                pass
        
        if collection_name not in self._collections:
            self._collections[collection_name] = self.client.get_or_create_collection(
                name=collection_name,
                metadata={"framework": framework}
            )
            self.logger.info(f"Collection ready: {collection_name}")
        
        return self._collections[collection_name]
    
    def add_documents(
        self,
        framework: str,
        documents: List[str],
        metadatas: List[Dict[str, Any]],
        ids: Optional[List[str]] = None
    ) -> int:
        """
        Add documents to a framework collection.
        
        Args:
            framework: Compliance framework name
            documents: List of document texts
            metadatas: List of metadata dictionaries
            ids: Optional list of document IDs
            
        Returns:
            Number of documents added
        """
        try:
            collection = self.get_or_create_collection(framework)
            
            # Generate embeddings
            self.logger.info(f"Generating embeddings for {len(documents)} documents...")
            embeddings = self.embedding_model.encode(
                documents,
                show_progress_bar=True,
                convert_to_numpy=True
            ).tolist()
            
            # Generate IDs if not provided
            if not ids:
                ids = [f"{framework}_{i}" for i in range(len(documents))]
            
            # Add to collection
            collection.add(
                documents=documents,
                embeddings=embeddings,
                metadatas=metadatas,
                ids=ids
            )
            
            self.logger.info(f"Added {len(documents)} documents to {framework} collection")
            return len(documents)
            
        except Exception as e:
            self.logger.error(f"Error adding documents: {e}", exc_info=True)
            return 0
    
    def query(
        self,
        framework: str,
        query_text: str,
        n_results: int = 5,
        where: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Query the vector store for relevant documents.
        
        Args:
            framework: Compliance framework name
            query_text: Query text
            n_results: Number of results to return
            where: Optional metadata filter
            
        Returns:
            Query results with documents, distances, and metadata
        """
        try:
            collection = self.get_or_create_collection(framework)
            
            # Generate query embedding
            query_embedding = self.embedding_model.encode(
                [query_text],
                convert_to_numpy=True
            ).tolist()
            
            # Query collection
            results = collection.query(
                query_embeddings=query_embedding,
                n_results=n_results,
                where=where
            )
            
            self.logger.debug(f"Query returned {len(results['documents'][0])} results")
            return results
            
        except Exception as e:
            self.logger.error(f"Error querying vector store: {e}", exc_info=True)
            return {'documents': [[]], 'distances': [[]], 'metadatas': [[]]}
    
    def query_multiple_frameworks(
        self,
        frameworks: List[str],
        query_text: str,
        n_results_per_framework: int = 3
    ) -> Dict[str, Dict[str, Any]]:
        """
        Query multiple frameworks at once.
        
        Args:
            frameworks: List of framework names
            query_text: Query text
            n_results_per_framework: Number of results per framework
            
        Returns:
            Dictionary mapping framework to query results
        """
        results = {}
        for framework in frameworks:
            results[framework] = self.query(
                framework=framework,
                query_text=query_text,
                n_results=n_results_per_framework
            )
        return results
    
    def get_collection_stats(self, framework: str) -> Dict[str, Any]:
        """
        Get statistics for a framework collection.
        
        Args:
            framework: Compliance framework name
            
        Returns:
            Dictionary with collection statistics
        """
        try:
            collection = self.get_or_create_collection(framework)
            count = collection.count()
            
            return {
                'framework': framework,
                'document_count': count,
                'collection_name': collection.name
            }
        except Exception as e:
            self.logger.error(f"Error getting collection stats: {e}")
            return {'framework': framework, 'document_count': 0, 'error': str(e)}
    
    def list_frameworks(self) -> List[str]:
        """
        List all available framework collections.
        
        Returns:
            List of framework names
        """
        try:
            collections = self.client.list_collections()
            frameworks = []
            for collection in collections:
                if collection.name.startswith('compliance_'):
                    framework = collection.name.replace('compliance_', '')
                    frameworks.append(framework)
            return frameworks
        except Exception as e:
            self.logger.error(f"Error listing frameworks: {e}")
            return []
    
    def delete_collection(self, framework: str) -> bool:
        """
        Delete a framework collection.
        
        Args:
            framework: Compliance framework name
            
        Returns:
            True if successful
        """
        try:
            collection_name = f"compliance_{framework.lower()}"
            self.client.delete_collection(collection_name)
            if collection_name in self._collections:
                del self._collections[collection_name]
            self.logger.info(f"Deleted collection: {collection_name}")
            return True
        except Exception as e:
            self.logger.error(f"Error deleting collection: {e}")
            return False

# Made with Bob
