from app.services.prompt_builder import PromptBuilder

contexts = [
    "Saudi Vision 2030 focuses on AI and digital transformation.",
    "ArabIQ is an enterprise AI platform.",
]

prompt = PromptBuilder.build_prompt(
    question="What is Saudi Vision 2030?",
    contexts=contexts,
)

print(prompt)