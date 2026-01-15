import shelve


class PersistentCounter:
    """Persistent counter using shelve database.
    
    Manages persistent key-value storage with automatic counting across sessions.
    Provides a dict-like interface with iteration, containment checks, and indexing.
    
    Attributes:
        cache_path (str): Path to shelve database
        enabled (bool): Enable/disable persistence
        _db: shelve.DbfilenameShelf instance
    
    Examples:
        >>> counter = PersistentCounter('my_cache.db')
        >>> counter.increment(['item1', 'item2'])
        >>> 'item1' in counter
        True
        >>> counter['item1']
        1
        >>> for key in counter:
        ...     print(f"{key}: {counter[key]}")
    """
    def __init__(self, cache_path='persistent_counter.db', enabled=True):
        """Initialize the persistent counter.
        
        Args:
            cache_path (str): Path to shelve database. Default: 'persistent_counter.db'
            enabled (bool): Enable persistence. Default: True
        """
        self.cache_path = cache_path
        self.enabled = enabled
        self._db = None
        if self.enabled:
            self._open()
    
    def _open(self):
        """Open the shelve database."""
        try:
            self._db = shelve.open(self.cache_path)
        except Exception as e:
            print(f"Warning: Could not open database at {self.cache_path}: {e}")
            self._db = None
    
    def increment(self, keys):
        """Increment counts for given keys.
        
        Args:
            keys (set or iterable): Keys to increment
        """
        if not self.enabled or self._db is None:
            return
        
        for key in keys:
            if key:
                try:
                    count = self._db.get(key, 0)
                    self._db[key] = count + 1
                    self._db.sync()
                except Exception as e:
                    print(f"Warning: Could not increment key '{key}': {e}")
    
    def get_all(self):
        """Retrieve all stored key-value pairs.
        
        Returns:
            dict: Keys mapped to their counts
        """
        if not self.enabled or self._db is None:
            return {}
        
        try:
            return dict(self._db)
        except Exception as e:
            print(f"Warning: Could not retrieve stored data: {e}")
            return {}
    
    def clear(self):
        """Clear all stored data."""
        if not self.enabled or self._db is None:
            return
        
        try:
            self._db.clear()
            self._db.sync()
        except Exception as e:
            print(f"Warning: Could not clear data: {e}")
    
    def close(self):
        """Close the database."""
        if self._db is not None:
            try:
                self._db.close()
                self._db = None
            except Exception as e:
                print(f"Warning: Could not close database: {e}")
    
    def __contains__(self, key):
        """Check if a key exists in the counter.
        
        Args:
            key: Key to check
            
        Returns:
            bool: True if key exists, False otherwise
        """
        if not self.enabled or self._db is None:
            return False
        try:
            return key in self._db
        except Exception:
            return False
    
    def __iter__(self):
        """Iterate over keys in the counter.
        
        Yields:
            Keys in the database
        """
        if not self.enabled or self._db is None:
            return iter([])
        try:
            return iter(self._db)
        except Exception:
            return iter([])
    
    def __len__(self):
        """Return the number of keys in the counter.
        
        Returns:
            int: Number of stored keys
        """
        if not self.enabled or self._db is None:
            return 0
        try:
            return len(self._db)
        except Exception:
            return 0
    
    def __getitem__(self, key):
        """Get the count for a key.
        
        Args:
            key: Key to retrieve
            
        Returns:
            int: Count for the key
            
        Raises:
            KeyError: If key does not exist
        """
        if not self.enabled or self._db is None:
            raise KeyError(key)
        try:
            return self._db[key]
        except KeyError:
            raise
        except Exception as e:
            raise KeyError(f"Error retrieving key '{key}': {e}")
    
    def __setitem__(self, key, value):
        """Set the count for a key.
        
        Args:
            key: Key to set
            value: Count value to set
        """
        if not self.enabled or self._db is None:
            return
        try:
            self._db[key] = value
            self._db.sync()
        except Exception as e:
            print(f"Warning: Could not set key '{key}': {e}")
