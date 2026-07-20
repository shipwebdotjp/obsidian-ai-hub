from obsidian_ai_hub.handler.obsidian_vault_retriever import search_obsidian_vault

if __name__ == "__main__":
    # Example usage of the synchronous search function
    query = "気になったURLをクリップして、要約して自分の関心事とどう関係あるのかなどを生成する"
    results = search_obsidian_vault.invoke(
        {
            "query": query,
            "k": 5,
            "search_mode": "hybrid",
        }
    )
    print(results)
