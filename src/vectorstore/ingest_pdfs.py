#!/usr/bin/env python3
"""
PDF ingestion script for compliance documents.
Extracts text from PDFs, chunks them, and stores in ChromaDB.
"""

import os
import sys
import logging
from pathlib import Path
from typing import List, Dict, Any
import pdfplumber
from utils import setup_logger
from vectorstore import ChromaComplianceStore


class PDFIngester:
    """Ingests compliance PDFs into vector store."""
    
    def __init__(
        self,
        chroma_store: ChromaComplianceStore,
        logger: logging.Logger
    ):
        """
        Initialize PDF ingester.
        
        Args:
            chroma_store: ChromaDB store instance
            logger: Logger instance
        """
        self.chroma_store = chroma_store
        self.logger = logger
    
    def extract_text_from_pdf(self, pdf_path: Path) -> str:
        """
        Extract text from PDF file.
        
        Args:
            pdf_path: Path to PDF file
            
        Returns:
            Extracted text
        """
        try:
            text = ""
            with pdfplumber.open(pdf_path) as pdf:
                for page in pdf.pages:
                    page_text = page.extract_text()
                    if page_text:
                        text += page_text + "\n"
            
            self.logger.info(f"Extracted {len(text)} characters from {pdf_path.name}")
            return text
            
        except Exception as e:
            self.logger.error(f"Error extracting text from {pdf_path}: {e}")
            return ""
    
    def chunk_text(
        self,
        text: str,
        chunk_size: int = 500,
        overlap: int = 50
    ) -> List[str]:
        """
        Split text into overlapping chunks.
        
        Args:
            text: Text to chunk
            chunk_size: Size of each chunk in tokens (approximate)
            overlap: Overlap between chunks in tokens
            
        Returns:
            List of text chunks
        """
        # Simple word-based chunking (approximate tokens)
        words = text.split()
        chunks = []
        
        i = 0
        while i < len(words):
            chunk_words = words[i:i + chunk_size]
            chunk = ' '.join(chunk_words)
            chunks.append(chunk)
            i += chunk_size - overlap
        
        self.logger.debug(f"Created {len(chunks)} chunks from text")
        return chunks
    
    def ingest_pdf(
        self,
        pdf_path: Path,
        framework: str,
        control_prefix: str = ""
    ) -> int:
        """
        Ingest a single PDF file.
        
        Args:
            pdf_path: Path to PDF file
            framework: Compliance framework name
            control_prefix: Prefix for control IDs
            
        Returns:
            Number of chunks ingested
        """
        try:
            self.logger.info(f"Ingesting PDF: {pdf_path.name} for framework: {framework}")
            
            # Extract text
            text = self.extract_text_from_pdf(pdf_path)
            if not text:
                self.logger.warning(f"No text extracted from {pdf_path.name}")
                return 0
            
            # Chunk text
            chunks = self.chunk_text(text)
            
            # Prepare metadata
            metadatas = []
            ids = []
            for i, chunk in enumerate(chunks):
                metadata = {
                    'framework': framework,
                    'source_file': pdf_path.name,
                    'chunk_index': i,
                    'control_id': f"{control_prefix}{i}" if control_prefix else f"chunk_{i}"
                }
                metadatas.append(metadata)
                ids.append(f"{framework}_{pdf_path.stem}_{i}")
            
            # Add to vector store
            count = self.chroma_store.add_documents(
                framework=framework,
                documents=chunks,
                metadatas=metadatas,
                ids=ids
            )
            
            self.logger.info(f"Successfully ingested {count} chunks from {pdf_path.name}")
            return count
            
        except Exception as e:
            self.logger.error(f"Error ingesting PDF {pdf_path}: {e}", exc_info=True)
            return 0
    
    def ingest_directory(
        self,
        directory: Path,
        framework_mapping: Dict[str, str]
    ) -> Dict[str, int]:
        """
        Ingest all PDFs from a directory.
        
        Args:
            directory: Directory containing PDF files
            framework_mapping: Mapping of filename patterns to frameworks
                              e.g., {'soc2': 'soc2', 'iso': 'iso27001'}
            
        Returns:
            Dictionary mapping framework to number of chunks ingested
        """
        results = {}
        
        if not directory.exists():
            self.logger.error(f"Directory not found: {directory}")
            return results
        
        pdf_files = list(directory.glob('*.pdf'))
        self.logger.info(f"Found {len(pdf_files)} PDF files in {directory}")
        
        for pdf_path in pdf_files:
            # Determine framework from filename
            framework = None
            for pattern, fw in framework_mapping.items():
                if pattern.lower() in pdf_path.name.lower():
                    framework = fw
                    break
            
            if not framework:
                self.logger.warning(
                    f"Could not determine framework for {pdf_path.name}, skipping"
                )
                continue
            
            # Ingest PDF
            count = self.ingest_pdf(pdf_path, framework)
            
            if framework not in results:
                results[framework] = 0
            results[framework] += count
        
        return results


def main():
    """Main entry point for PDF ingestion."""
    # Setup logger
    logger = setup_logger(
        name='pdf_ingester',
        log_level='INFO',
        log_dir='logs'
    )
    
    logger.info("=" * 60)
    logger.info("Compliance PDF Ingestion")
    logger.info("=" * 60)
    
    # Initialize ChromaDB store
    chroma_store = ChromaComplianceStore(
        persist_directory='src/vectorstore/chroma_data',
        embedding_model='sentence-transformers/all-MiniLM-L6-v2',
        logger=logger
    )
    
    # Initialize ingester
    ingester = PDFIngester(chroma_store, logger)
    
    # Define compliance docs directory
    docs_dir = Path('compliance_docs')
    
    if not docs_dir.exists():
        logger.error(f"Compliance docs directory not found: {docs_dir}")
        logger.info("Please create 'compliance_docs' directory and add PDF files")
        sys.exit(1)
    
    # Define framework mapping
    # Map filename patterns to framework names
    framework_mapping = {
        'soc2': 'soc2',
        'soc_2': 'soc2',
        'iso27001': 'iso27001',
        'iso_27001': 'iso27001',
        'iso-27001': 'iso27001',
        'hipaa': 'hipaa',
        'pci': 'pci_dss',
        'pci-dss': 'pci_dss',
        'gdpr': 'gdpr',
        'fedramp': 'fedramp'
    }
    
    # Ingest PDFs
    logger.info(f"\nScanning directory: {docs_dir}")
    results = ingester.ingest_directory(docs_dir, framework_mapping)
    
    # Print summary
    logger.info("\n" + "=" * 60)
    logger.info("Ingestion Complete!")
    logger.info("=" * 60)
    
    if results:
        logger.info("\nIngested chunks by framework:")
        total_chunks = 0
        for framework, count in results.items():
            logger.info(f"  - {framework}: {count} chunks")
            total_chunks += count
        logger.info(f"\nTotal chunks ingested: {total_chunks}")
    else:
        logger.warning("No PDFs were ingested. Check filename patterns and framework mapping.")
    
    # Show available frameworks
    frameworks = chroma_store.list_frameworks()
    if frameworks:
        logger.info(f"\nAvailable frameworks in vector store: {', '.join(frameworks)}")
    
    logger.info("=" * 60)


if __name__ == '__main__':
    main()

# Made with Bob
