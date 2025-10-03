"""
Simple database connection and operations
"""

import json
import pymysql
from typing import Dict, List, Any, Optional
import logging
from .properties_config import get_properties_config

logger = logging.getLogger(__name__)


class DatabaseManager:
    """Simple database manager for JSON data storage"""
    
    def __init__(self):
        """Initialize database connection"""
        self.config = get_properties_config()
        self.connection = None
        self._connect()
    
    def _connect(self):
        """Connect to MySQL database"""
        try:
            # Extract connection parameters from config
            jdbc_url = self.config.get_database_url()
            # Parse jdbc:mysql://localhost:3306/senior_project
            if jdbc_url.startswith('jdbc:mysql://'):
                url_part = jdbc_url.replace('jdbc:mysql://', '')
                if '/' in url_part:
                    host_port, database = url_part.split('/', 1)
                    if ':' in host_port:
                        host, port = host_port.split(':')
                        port = int(port)
                    else:
                        host = host_port
                        port = 3306
                else:
                    host = 'localhost'
                    port = 3306
                    database = 'senior_project'
            else:
                host = 'localhost'
                port = 3306
                database = 'senior_project'
            
            username = self.config.get_database_username()
            password = self.config.get_database_password()
            
            # Connect to MySQL
            self.connection = pymysql.connect(
                host=host,
                port=port,
                user=username,
                password=password,
                database=database,
                charset='utf8mb4',
                autocommit=True
            )
            
            logger.info(f"Connected to MySQL database: {database}")
            
        except Exception as e:
            logger.error(f"Failed to connect to database: {e}")
            raise
    
    def store_json_file(self, file_name: str, json_data: Any) -> int:
        """
        Store JSON data to database
        
        Args:
            file_name: Name of the JSON file
            json_data: JSON data (dict or list)
            
        Returns:
            file_index: The index (PK) of the stored file
        """
        try:
            cursor = self.connection.cursor()
            
            # Flatten JSON data and store
            flattened_data = self._flatten_json(json_data)
            
            # Insert data into database (let AUTO_INCREMENT handle the index)
            insert_sql = "INSERT INTO `json` (`key`, `value`, `file_name`) VALUES (%s, %s, %s)"
            
            for key, value in flattened_data.items():
                cursor.execute(insert_sql, (key, str(value), file_name))
            
            # Get the generated index (should be the same for all records of this file)
            cursor.execute("SELECT `index` FROM `json` WHERE `file_name` = %s ORDER BY `index` DESC LIMIT 1", (file_name,))
            result = cursor.fetchone()
            file_index = result[0] if result else None
            
            logger.info(f"Stored JSON file '{file_name}' with index {file_index}, {len(flattened_data)} records")
            return file_index
            
        except Exception as e:
            logger.error(f"Failed to store JSON file: {e}")
            raise
    
    def _flatten_json(self, data: Any, parent_key: str = '') -> Dict[str, Any]:
        """
        Flatten JSON data into key-value pairs
        
        Args:
            data: JSON data to flatten
            parent_key: Parent key for nested objects
            
        Returns:
            Flattened dictionary
        """
        items = []
        
        if isinstance(data, dict):
            for key, value in data.items():
                new_key = f"{parent_key}.{key}" if parent_key else key
                if isinstance(value, (dict, list)):
                    items.extend(self._flatten_json(value, new_key).items())
                else:
                    items.append((new_key, value))
        
        elif isinstance(data, list):
            for i, value in enumerate(data):
                new_key = f"{parent_key}[{i}]" if parent_key else f"[{i}]"
                if isinstance(value, (dict, list)):
                    items.extend(self._flatten_json(value, new_key).items())
                else:
                    items.append((new_key, value))
        
        else:
            # Primitive value
            items.append((parent_key, data))
        
        return dict(items)
    
    def get_json_by_index(self, index: int) -> Dict[str, Any]:
        """
        Retrieve JSON data by index
        
        Args:
            index: File index
            
        Returns:
            Dictionary with file_name and flattened data
        """
        try:
            cursor = self.connection.cursor()
            cursor.execute("SELECT `key`, `value`, `file_name` FROM `json` WHERE `index` = %s", (index,))
            results = cursor.fetchall()
            
            if not results:
                return {}
            
            data = {}
            file_name = results[0][2]  # file_name is the same for all records
            
            for key, value, _ in results:
                data[key] = value
            
            return {
                'file_name': file_name,
                'data': data
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
            cursor = self.connection.cursor()
            cursor.execute("""
                SELECT `index`, `file_name`, COUNT(*) as record_count 
                FROM `json` 
                GROUP BY `index`, `file_name` 
                ORDER BY `index`
            """)
            results = cursor.fetchall()
            
            files = []
            for index, file_name, record_count in results:
                files.append({
                    'index': index,
                    'file_name': file_name,
                    'record_count': record_count
                })
            
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
            cursor = self.connection.cursor()
            cursor.execute("DELETE FROM `json` WHERE `index` = %s", (index,))
            affected_rows = cursor.rowcount
            
            logger.info(f"Deleted JSON data with index {index}, {affected_rows} records removed")
            return affected_rows > 0
            
        except Exception as e:
            logger.error(f"Failed to delete JSON data: {e}")
            raise
    
    def close(self):
        """Close database connection"""
        if self.connection:
            self.connection.close()
            logger.info("Database connection closed")
    
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
