"""
Properties configuration file manager
"""

import os
from pathlib import Path
from typing import Dict, Any, Optional
import logging

logger = logging.getLogger(__name__)


class PropertiesConfig:
    """Properties configuration file manager"""
    
    def __init__(self, config_path: str = None):
        """
        Initialize Properties configuration manager
        
        Args:
            config_path: Configuration file path, defaults to config/application.properties
        """
        if config_path is None:
            # Default configuration file path
            current_dir = Path(__file__).parent
            config_path = current_dir.parent / "config" / "application.properties"
        
        self.config_path = Path(config_path)
        self._config = {}
        self._load_config()
    
    def _load_config(self):
        """Load properties configuration file"""
        try:
            if self.config_path.exists():
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    for line in f:
                        line = line.strip()
                        # Skip empty lines and comment lines
                        if not line or line.startswith('#'):
                            continue
                        
                        # Parse key=value format
                        if '=' in line:
                            key, value = line.split('=', 1)
                            key = key.strip()
                            value = value.strip()
                            
                            # Handle boolean values
                            if value.lower() in ('true', 'false'):
                                value = value.lower() == 'true'
                            # Keep passwords as strings (don't convert to int)
                            elif key.endswith('password'):
                                value = str(value)
                            # Handle numbers
                            elif value.isdigit():
                                value = int(value)
                            
                            self._config[key] = value
                
                logger.info(f"Properties configuration file loaded successfully: {self.config_path}")
            else:
                logger.warning(f"Configuration file does not exist: {self.config_path}")
                self._create_default_config()
        except Exception as e:
            logger.error(f"Failed to load configuration file: {e}")
            self._create_default_config()
    
    def _create_default_config(self):
        """Create default configuration"""
        self._config = {
            'spring.datasource.url': 'jdbc:mysql://localhost:3306/senior_project',
            'spring.datasource.username': 'Beiming',
            'spring.datasource.password': '518105309',
            'spring.datasource.driver-class-name': 'com.mysql.cj.jdbc.Driver'
        }
        logger.info("Using default database configuration")
    
    def get(self, key: str, default: Any = None) -> Any:
        """Get configuration value"""
        return self._config.get(key, default)
    
    def set(self, key: str, value: Any):
        """Set configuration value"""
        self._config[key] = value
    
    def get_database_url(self) -> str:
        """Get database URL"""
        return self.get('spring.datasource.url', 'jdbc:mysql://localhost:3306/senior_project')
    
    def get_database_username(self) -> str:
        """Get database username"""
        return self.get('spring.datasource.username', 'Beiming')
    
    def get_database_password(self) -> str:
        """Get database password"""
        return self.get('spring.datasource.password', '518105309')
    
    def get_database_driver(self) -> str:
        """Get database driver"""
        return self.get('spring.datasource.driver-class-name', 'com.mysql.cj.jdbc.Driver')
    
    def get_connection_pool_size(self) -> int:
        """Get connection pool size"""
        return self.get('spring.datasource.hikari.maximum-pool-size', 10)
    
    def get_connection_timeout(self) -> int:
        """Get connection timeout"""
        return self.get('spring.datasource.hikari.connection-timeout', 30000)
    
    def get_app_name(self) -> str:
        """Get application name"""
        return self.get('app.name', 'JSON-Tool')
    
    def get_app_version(self) -> str:
        """Get application version"""
        return self.get('app.version', '1.0.0')
    
    def is_auto_connect(self) -> bool:
        """Whether to auto-connect to database"""
        return self.get('app.database.auto-connect', True)
    
    def get_retry_attempts(self) -> int:
        """Get retry attempts"""
        return self.get('app.database.retry-attempts', 3)
    
    def get_retry_delay(self) -> int:
        """Get retry delay"""
        return self.get('app.database.retry-delay', 1)
    
    def get_mysql_connection_string(self) -> str:
        """Get MySQL connection string (for Python)"""
        # Convert JDBC URL to Python MySQL connection string
        jdbc_url = self.get_database_url()
        # jdbc:mysql://localhost:3306/senior_project -> mysql://username:password@localhost:3306/senior_project
        if jdbc_url.startswith('jdbc:mysql://'):
            mysql_url = jdbc_url.replace('jdbc:mysql://', 'mysql://')
            username = self.get_database_username()
            password = self.get_database_password()
            # Insert username and password
            mysql_url = mysql_url.replace('mysql://', f'mysql://{username}:{password}@')
            return mysql_url
        return jdbc_url
    
    def save_config(self):
        """Save configuration to file"""
        try:
            # Ensure configuration directory exists
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            
            with open(self.config_path, 'w', encoding='utf-8') as f:
                f.write("# Database Configuration\n")
                f.write(f"spring.datasource.url={self.get_database_url()}\n")
                f.write(f"spring.datasource.username={self.get_database_username()}\n")
                f.write(f"spring.datasource.password={self.get_database_password()}\n")
                f.write(f"spring.datasource.driver-class-name={self.get_database_driver()}\n")
                f.write("\n")
                f.write("# Connection Pool Settings\n")
                f.write(f"spring.datasource.hikari.maximum-pool-size={self.get_connection_pool_size()}\n")
                f.write(f"spring.datasource.hikari.connection-timeout={self.get_connection_timeout()}\n")
                f.write("\n")
                f.write("# Application Settings\n")
                f.write(f"app.name={self.get_app_name()}\n")
                f.write(f"app.version={self.get_app_version()}\n")
                f.write(f"app.database.auto-connect={self.is_auto_connect()}\n")
                f.write(f"app.database.retry-attempts={self.get_retry_attempts()}\n")
                f.write(f"app.database.retry-delay={self.get_retry_delay()}\n")
            
            logger.info(f"Configuration file saved successfully: {self.config_path}")
        except Exception as e:
            logger.error(f"Failed to save configuration file: {e}")
            raise
    
    def get_config_summary(self) -> Dict[str, Any]:
        """Get configuration summary"""
        return {
            "app_name": self.get_app_name(),
            "app_version": self.get_app_version(),
            "database_url": self.get_database_url(),
            "database_username": self.get_database_username(),
            "connection_pool_size": self.get_connection_pool_size(),
            "auto_connect": self.is_auto_connect()
        }


# Global configuration instance
_config_instance = None

def get_properties_config() -> PropertiesConfig:
    """Get global Properties configuration instance"""
    global _config_instance
    if _config_instance is None:
        _config_instance = PropertiesConfig()
    return _config_instance
