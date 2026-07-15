from app.services.llm import LLMFactory

provider = LLMFactory.get_provider()

print("=" * 60)

print("Provider:", type(provider).__name__)

print("Health:", provider.health_check())