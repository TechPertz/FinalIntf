import os


OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "your_default_openai_api_key")
NEO4J_URI = "neo4j://localhost:7687"
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "mypassword123")
