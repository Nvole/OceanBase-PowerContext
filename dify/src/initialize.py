from db import initialize_database
from debate import ensure_ready


if __name__ == "__main__":
    database = initialize_database()
    collection = ensure_ready()
    print(f"Initialized dedicated database {database}; seed count={collection.count()}")
