import argparse
import os
from config import LLMConfig, EmailConfig, CommonConfig
from sources import SOURCE_REGISTRY
from llm.codex_bridge import (
    DEFAULT_BRIDGE_URL,
    DEFAULT_ISSUER,
    DEFAULT_API_BASE,
    ensure_local_bridge,
    stop_local_bridge,
)


def load_dotenv(path: str = ".env") -> None:
    """Load simple KEY=VALUE pairs from .env without overriding real env vars."""
    if not os.path.exists(path):
        return

    with open(path, "r", encoding="utf-8") as f:
        for raw_line in f:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue

            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip()

            if key.startswith("export "):
                key = key[len("export "):].strip()

            if value and value[0] == value[-1] and value[0] in ("'", '"'):
                value = value[1:-1]

            os.environ.setdefault(key, value)


def env_str(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name)
    if value in (None, ""):
        return default
    return value


def env_int(name: str, default: int | None = None) -> int | None:
    value = os.getenv(name)
    if value in (None, ""):
        return default
    return int(value)


def env_float(name: str, default: float | None = None) -> float | None:
    value = os.getenv(name)
    if value in (None, ""):
        return default
    return float(value)


def main():
    load_dotenv()

    parser = argparse.ArgumentParser(description="Unified Daily Recommender")

    parser.add_argument(
        "--sources", nargs="+", required=True,
        choices=list(SOURCE_REGISTRY.keys()),
        help=f"Information sources to run: {list(SOURCE_REGISTRY.keys())}",
    )

    # LLM config
    parser.add_argument(
        "--provider", type=str,
        default=env_str("LLM_PROVIDER"),
        required=env_str("LLM_PROVIDER") is None,
        help="LLM provider (or set LLM_PROVIDER in .env)",
    )
    parser.add_argument(
        "--model", type=str,
        default=env_str("LLM_MODEL"),
        required=env_str("LLM_MODEL") is None,
        help="Model name (or set LLM_MODEL in .env)",
    )
    parser.add_argument(
        "--base_url", type=str, default=env_str("LLM_BASE_URL"),
        help="API base URL (or set LLM_BASE_URL in .env)",
    )
    parser.add_argument(
        "--api_key", type=str, default=env_str("LLM_API_KEY"),
        help="API key (or set LLM_API_KEY in .env)",
    )
    parser.add_argument(
        "--auth_mode",
        type=str,
        choices=("api_key", "codex_bridge"),
        default=env_str("LLM_AUTH_MODE", "api_key"),
        help="LLM auth mode: direct API key or local Codex auth bridge",
    )
    parser.add_argument(
        "--codex_auth_file",
        type=str,
        default=env_str("CODEX_AUTH_FILE", os.path.expanduser("~/.codex/auth.json")),
        help="Path to Codex auth.json for codex_bridge mode",
    )
    parser.add_argument(
        "--codex_bridge_url",
        type=str,
        default=env_str("CODEX_BRIDGE_URL", DEFAULT_BRIDGE_URL),
        help="Local Codex bridge base URL",
    )
    parser.add_argument(
        "--codex_bridge_issuer",
        type=str,
        default=env_str("CODEX_BRIDGE_ISSUER", DEFAULT_ISSUER),
        help="OAuth issuer used by the Codex bridge",
    )
    parser.add_argument(
        "--codex_api_base",
        type=str,
        default=env_str("CODEX_API_BASE", DEFAULT_API_BASE),
        help="Upstream OpenAI API base used by the Codex bridge",
    )
    parser.add_argument(
        "--codex_bridge_start_timeout",
        type=float,
        default=env_float("CODEX_BRIDGE_START_TIMEOUT", 15.0),
        help="Seconds to wait for the local Codex bridge to become healthy",
    )
    parser.add_argument(
        "--temperature", type=float, default=env_float("LLM_TEMPERATURE", 0.7), help="Temperature"
    )

    # Email config
    parser.add_argument("--smtp_server", type=str, default=env_str("SMTP_SERVER"), help="SMTP server")
    parser.add_argument("--smtp_port", type=int, default=env_int("SMTP_PORT"), help="SMTP port")
    parser.add_argument("--sender", type=str, default=env_str("SMTP_SENDER"), help="Sender email")
    parser.add_argument(
        "--receiver", type=str, default=env_str("SMTP_RECEIVER"), help="Receiver email(s), comma separated"
    )
    parser.add_argument(
        "--sender_password", type=str, default=env_str("SMTP_PASSWORD"), help="Sender email password"
    )

    # Common config
    parser.add_argument(
        "--description", type=str, default=os.getenv("DESCRIPTION_FILE", "description.txt"),
        help="Interest description file path"
    )
    parser.add_argument(
        "--num_workers", type=int, default=env_int("NUM_WORKERS", 4), help="Number of parallel workers"
    )
    parser.add_argument("--save", action="store_true", help="Save results to history")
    parser.add_argument("--save_dir", type=str, default="./history", help="History save directory")

    # Idea generation config
    parser.add_argument("--generate_ideas", action="store_true", help="Generate research ideas from recommendations")
    parser.add_argument("--researcher_profile", type=str, default="researcher_profile.md",
                        help="Path to researcher profile for idea generation")
    parser.add_argument("--idea_min_score", type=float, default=7, help="Min score for idea generation input")
    parser.add_argument("--idea_max_items", type=int, default=15, help="Max items to feed into idea generator")
    parser.add_argument("--idea_count", type=int, default=5, help="Number of ideas to generate")

    # Register each source's specific arguments
    for source_name, source_cls in SOURCE_REGISTRY.items():
        source_cls.add_arguments(parser)

    args = parser.parse_args()

    # Validate LLM config
    if args.generate_ideas and not args.save:
        raise ValueError("--generate_ideas requires --save so ideas.json is available for /idea-from-daily")
    if args.generate_ideas and not os.path.exists(args.researcher_profile):
        raise FileNotFoundError(f"Researcher profile not found: {args.researcher_profile}")
    provider = args.provider.lower()
    auth_mode = args.auth_mode.lower()
    resolved_base_url = args.base_url
    resolved_api_key = args.api_key
    if provider != "ollama":
        if auth_mode == "codex_bridge":
            if provider != "openai":
                raise ValueError("codex_bridge is only supported with provider=openai")
            resolved_base_url = args.codex_bridge_url
            resolved_api_key = resolved_api_key or "codex-bridge"
        else:
            assert resolved_base_url, "base_url is required for OpenAI/SiliconFlow"
            assert resolved_api_key, "api_key is required for OpenAI/SiliconFlow"

    # Load description
    with open(args.description, "r", encoding="utf-8") as f:
        description_text = f.read()

    # Build configs
    llm_config = LLMConfig(
        provider=args.provider,
        model=args.model,
        base_url=resolved_base_url,
        api_key=resolved_api_key,
        temperature=args.temperature,
        auth_mode=auth_mode,
        codex_auth_file=args.codex_auth_file,
        codex_bridge_issuer=args.codex_bridge_issuer,
        codex_api_base=args.codex_api_base,
        codex_bridge_start_timeout=args.codex_bridge_start_timeout,
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
    bridge_process = None
    try:
        if llm_config.auth_mode == "codex_bridge":
            bridge_process = ensure_local_bridge(
                bridge_url=llm_config.base_url,
                auth_file=llm_config.codex_auth_file or os.path.expanduser("~/.codex/auth.json"),
                issuer=llm_config.codex_bridge_issuer,
                api_base=llm_config.codex_api_base,
                startup_timeout=llm_config.codex_bridge_start_timeout,
            )

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
        all_recs = {}
        for source_name in args.sources:
            print(f"\n{'='*60}")
            print(f"Running source: {source_name}")
            print(f"{'='*60}")

            source_cls = SOURCE_REGISTRY[source_name]
            source_args = source_cls.extract_args(args)

            source = source_cls(source_args, llm_config, common_config)
            recs = source.send_email(email_config)
            all_recs[source_name] = recs or []

        if args.generate_ideas:
            print(f"\n{'='*60}")
            print("Generating research ideas...")
            print(f"{'='*60}")

            from idea_generator import IdeaGenerator

            generator = IdeaGenerator(
                all_recs=all_recs,
                profile_path=args.researcher_profile,
                llm_config=llm_config,
                common_config=common_config,
                min_score=args.idea_min_score,
                max_items=args.idea_max_items,
                idea_count=args.idea_count,
            )
            ideas = generator.generate()
            if ideas:
                generator.save(ideas)
                generator.send_email(ideas, email_config)
            else:
                print("No ideas generated.")

        print(f"\nAll sources completed: {args.sources}")
    finally:
        stop_local_bridge(bridge_process)


if __name__ == "__main__":
    main()
