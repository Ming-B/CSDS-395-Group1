"""
File-based storage for JSON data (Git-friendly)
Replaces MySQL database with file system storage
"""

import json
from pathlib import Path
from typing import Dict, List, Any, Optional
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


class DatabaseManager:
    """File-based storage manager for JSON data"""
    
    def __init__(self):
        """Initialize file storage"""
        # Get project root directory
        current_dir = Path(__file__).parent
        root_dir = current_dir.parent
        
        # Storage directory structure
        self.storage_dir = root_dir / "stored_files"
        self.files_dir = self.storage_dir / "files"
        self.index_file = self.storage_dir / "index.json"
        
        # Create directories if they don't exist
        self.files_dir.mkdir(parents=True, exist_ok=True)
        
        # Initialize index if it doesn't exist
        self._ensure_index()
        
        logger.info(f"Initialized file storage at: {self.storage_dir}")
    
    def _ensure_index(self):
        """Ensure index file exists"""
        if not self.index_file.exists():
            index_data = {
                "next_index": 1,
                "files": []
            }
            self._save_index(index_data)
    
    def _load_index(self) -> Dict[str, Any]:
        """Load index file"""
        try:
            with open(self.index_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load index: {e}")
            # Return empty index if load fails
            return {"next_index": 1, "files": []}
    
    def _save_index(self, index_data: Dict[str, Any]):
        """Save index file"""
        try:
            with open(self.index_file, 'w', encoding='utf-8') as f:
                json.dump(index_data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Failed to save index: {e}")
            raise
    
    def store_json_file(self, file_name: str, json_data: Any) -> int:
        """
        Store JSON data to file system
        
        Args:
            file_name: Name of the JSON file
            json_data: JSON data (dict or list)
            
        Returns:
            file_index: The index of the stored file
        """
        try:
            # Load index
            index_data = self._load_index()
            
            # Get next index
            file_index = index_data["next_index"]
            index_data["next_index"] += 1
            
            # Create safe filename (remove invalid characters)
            safe_name = "".join(c for c in file_name if c.isalnum() or c in ('-', '_', '.'))
            if not safe_name:
                safe_name = "file"
            
            # Save JSON file
            file_path = self.files_dir / f"{file_index:04d}_{safe_name}.json"
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(json_data, f, indent=2, ensure_ascii=False)
            
            # Add to index
            file_info = {
                "index": file_index,
                "file_name": file_name,
                "stored_file": file_path.name,
                "stored_at": datetime.now().isoformat(),
                "record_count": len(json_data) if isinstance(json_data, (list, dict)) else 1
            }
            index_data["files"].append(file_info)
            
            # Save index
            self._save_index(index_data)
            
            logger.info(f"Stored JSON file '{file_name}' with index {file_index} to {file_path}")
            return file_index
            
        except Exception as e:
            logger.error(f"Failed to store JSON file: {e}")
            raise
    
    def get_json_by_index(self, index: int) -> Dict[str, Any]:
        """
        Retrieve JSON data by index
        
        Args:
            index: File index
            
        Returns:
            Dictionary with file_name and data
        """
        try:
            # Load index
            index_data = self._load_index()
            
            # Find file info
            file_info = None
            for f in index_data["files"]:
                if f["index"] == index:
                    file_info = f
                    break
            
            if not file_info:
                return {}
            
            # Load JSON file
            file_path = self.files_dir / file_info["stored_file"]
            if not file_path.exists():
                logger.error(f"Stored file not found: {file_path}")
                return {}
            
            with open(file_path, 'r', encoding='utf-8') as f:
                json_data = json.load(f)
            
            return {
                'file_name': file_info["file_name"],
                'data': json_data
            }
            
        except Exception as e:
            logger.error(f"Failed to retrieve JSON data: {e}")
            raise
    
    def get_all_files(self) -> List[Dict[str, Any]]:
        """
        Get list of all stored JSON files
        
        Returns:
            List of file information
        """
        try:
            index_data = self._load_index()
            
            files = []
            for f in index_data["files"]:
                files.append({
                    'index': f["index"],
                    'file_name': f["file_name"],
                    'record_count': f.get("record_count", 0)
                })
            
            # Sort by index
            files.sort(key=lambda x: x['index'])
            
            return files
            
        except Exception as e:
            logger.error(f"Failed to get file list: {e}")
            raise
    
    def delete_json_by_index(self, index: int) -> bool:
        """
        Delete JSON data by index
        
        Args:
            index: File index to delete
            
        Returns:
            True if successful
        """
        try:
            # Load index
            index_data = self._load_index()
            
            # Find and remove file info
            file_info = None
            for i, f in enumerate(index_data["files"]):
                if f["index"] == index:
                    file_info = f
                    index_data["files"].pop(i)
                    break
            
            if not file_info:
                logger.warning(f"File with index {index} not found")
                return False
            
            # Delete file
            file_path = self.files_dir / file_info["stored_file"]
            if file_path.exists():
                file_path.unlink()
            
            # Save index
            self._save_index(index_data)
            
            logger.info(f"Deleted JSON data with index {index}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to delete JSON data: {e}")
            raise
    
    def close(self):
        """Close storage (no-op for file storage)"""
        logger.debug("File storage closed")
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


# Global database manager instance
_db_manager = None

def get_database_manager() -> DatabaseManager:
    """Get global database manager instance"""
    global _db_manager
    if _db_manager is None:
        _db_manager = DatabaseManager()
    return _db_manager
