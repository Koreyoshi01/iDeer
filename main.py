import argparse
import os
from config import LLMConfig, EmailConfig, CommonConfig
from sources import SOURCE_REGISTRY


def main():
    parser = argparse.ArgumentParser(description="Unified Daily Recommender")

    parser.add_argument(
        "--sources", nargs="+", required=True,
        choices=list(SOURCE_REGISTRY.keys()),
        help=f"Information sources to run: {list(SOURCE_REGISTRY.keys())}",
    )

    # LLM config
    parser.add_argument("--provider", type=str, required=True, help="LLM provider")
    parser.add_argument("--model", type=str, required=True, help="Model name")
    parser.add_argument("--base_url", type=str, default=None, help="API base URL")
    parser.add_argument("--api_key", type=str, default=None, help="API key")
    parser.add_argument("--temperature", type=float, default=0.7, help="Temperature")

    # Email config
    parser.add_argument("--smtp_server", type=str, help="SMTP server")
    parser.add_argument("--smtp_port", type=int, help="SMTP port")
    parser.add_argument("--sender", type=str, help="Sender email")
    parser.add_argument("--receiver", type=str, help="Receiver email(s), comma separated")
    parser.add_argument("--sender_password", type=str, help="Sender email password")

    # Common config
    parser.add_argument("--description", type=str, default="description.txt", help="Interest description file path")
    parser.add_argument("--num_workers", type=int, default=4, help="Number of parallel workers")
    parser.add_argument("--save", action="store_true", help="Save results to history")
    parser.add_argument("--save_dir", type=str, default="./history", help="History save directory")

    # Register each source's specific arguments
    for source_name, source_cls in SOURCE_REGISTRY.items():
        source_cls.add_arguments(parser)

    args = parser.parse_args()

    # Validate LLM config
    if args.provider.lower() != "ollama":
        assert args.base_url is not None, "base_url is required for OpenAI/SiliconFlow"
        assert args.api_key is not None, "api_key is required for OpenAI/SiliconFlow"

    # Load description
    with open(args.description, "r", encoding="utf-8") as f:
        description_text = f.read()

    # Build configs
    llm_config = LLMConfig(
        provider=args.provider,
        model=args.model,
        base_url=args.base_url,
        api_key=args.api_key,
        temperature=args.temperature,
    )
    email_config = EmailConfig(
        smtp_server=args.smtp_server,
        smtp_port=args.smtp_port,
        sender=args.sender,
        receiver=args.receiver,
        sender_password=args.sender_password,
    )
    common_config = CommonConfig(
        description=description_text,
        num_workers=args.num_workers,
        save=args.save,
        save_dir=args.save_dir,
    )

    # Test LLM availability once
    print("Testing LLM availability...")
    if llm_config.provider.lower() == "ollama":
        from llm.Ollama import Ollama
        test_model = Ollama(llm_config.model)
    else:
        from llm.GPT import GPT
        test_model = GPT(llm_config.model, llm_config.base_url, llm_config.api_key)
    try:
        test_model.inference("Hello, who are you?")
        print("LLM is available.")
    except Exception as e:
        print(f"LLM test failed: {e}")
        raise RuntimeError("LLM not available, aborting.")

    # Run each source
    for source_name in args.sources:
        print(f"\n{'='*60}")
        print(f"Running source: {source_name}")
        print(f"{'='*60}")

        source_cls = SOURCE_REGISTRY[source_name]
        source_args = source_cls.extract_args(args)

        source = source_cls(source_args, llm_config, common_config)
        source.send_email(email_config)

    print(f"\nAll sources completed: {args.sources}")


if __name__ == "__main__":
    main()
