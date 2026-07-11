from databricks_zh_expert.llm.model_registry import (
    MODEL_ALIASES,
    MODEL_SPECS,
    ModelAlias,
    ModelProvider,
    ModelRegistry,
)


def test_registry_exposes_only_the_fixed_model_aliases(settings_factory) -> None:
    registry = ModelRegistry.from_settings(
        settings_factory(openai_api_key="openai-key", deepseek_api_key=None)
    )

    assert MODEL_ALIASES == (
        ModelAlias.GPT_55,
        ModelAlias.GPT_54_MINI,
        ModelAlias.DEEPSEEK_V4_FLASH,
        ModelAlias.DEEPSEEK_V4_PRO,
    )
    assert [model.alias for model in registry.models] == list(MODEL_ALIASES)
    assert registry.get(ModelAlias.GPT_55).litellm_model == "openai/gpt-5.5"
    assert registry.get(ModelAlias.DEEPSEEK_V4_FLASH).provider is ModelProvider.DEEPSEEK
    assert registry.default_model is ModelAlias.DEEPSEEK_V4_FLASH
    assert registry.fallback_models == (
        ModelAlias.DEEPSEEK_V4_FLASH,
        ModelAlias.GPT_54_MINI,
    )


def test_model_specs_are_the_single_fixed_model_catalog() -> None:
    assert [
        (
            spec.alias.value,
            spec.display_name,
            spec.provider.value,
            spec.litellm_model,
        )
        for spec in MODEL_SPECS
    ] == [
        ("gpt5.5", "GPT-5.5", "openai", "openai/gpt-5.5"),
        ("gpt5.4mini", "GPT-5.4 mini", "openai", "openai/gpt-5.4-mini"),
        (
            "deepseek-v4-flash",
            "DeepSeek V4 Flash",
            "deepseek",
            "deepseek/deepseek-v4-flash",
        ),
        (
            "deepseek-v4-pro",
            "DeepSeek V4 Pro",
            "deepseek",
            "deepseek/deepseek-v4-pro",
        ),
    ]


def test_registry_reports_provider_key_configuration(settings_factory) -> None:
    registry = ModelRegistry.from_settings(
        settings_factory(openai_api_key="openai-key", deepseek_api_key=None)
    )

    assert registry.get(ModelAlias.GPT_55).configured is True
    assert registry.get(ModelAlias.GPT_54_MINI).configured is True
    assert registry.get(ModelAlias.DEEPSEEK_V4_FLASH).configured is False
    assert registry.get(ModelAlias.DEEPSEEK_V4_PRO).configured is False
