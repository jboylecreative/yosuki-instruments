from pydantic import BaseModel, field_validator
from typing import Optional


class AssetVariant(BaseModel):
    id: str
    color: Optional[str] = None
    asset_png: str
    asset_glb: Optional[str] = None


class ProductModel(BaseModel):
    id: str
    name: str
    variants: list[AssetVariant]
    aspect_ratios: list[str]


class CreativeDirection(BaseModel):
    scene: str
    vibe: str
    visual_motif: str


class Product(BaseModel):
    id: str
    series: str
    key_message: str
    models: list[ProductModel]
    creative_direction: CreativeDirection
    target_audience: Optional[str] = None


class LocaleCreativeOverride(BaseModel):
    scene_override: Optional[str] = None


class Locale(BaseModel):
    id: str
    language: str
    cultural_tone: str
    locale_creative_overrides: dict[str, LocaleCreativeOverride] = {}


class CharacterLimits(BaseModel):
    tagline: int = 40
    cta: int = 25
    product_name: int = 50


class CampaignBrief(BaseModel):
    campaign_name: str
    client: str
    launch_window: str
    locales: list[Locale]
    products: list[Product]
    character_limits: CharacterLimits


class AssetMatch(BaseModel):
    product_id: str
    model_id: str
    variant_id: str
    asset_png: str
    asset_glb: Optional[str] = None
    match_confidence: float
    description: str


class AssetManifest(BaseModel):
    matches: list[AssetMatch]
    warnings: list[str] = []


class LocaleCopy(BaseModel):
    tagline: str
    cta: str
    product_name: str
    background_prompt_stage1: str
    background_prompt_stage2: str

    @field_validator("tagline")
    @classmethod
    def tagline_length(cls, v: str) -> str:
        if len(v) > 40:
            raise ValueError(f"Tagline '{v}' exceeds 40 chars ({len(v)})")
        return v

    @field_validator("cta")
    @classmethod
    def cta_length(cls, v: str) -> str:
        if len(v) > 25:
            raise ValueError(f"CTA '{v}' exceeds 25 chars ({len(v)})")
        return v


class VariantCopy(BaseModel):
    product_id: str
    model_id: str
    variant_id: str
    locales: dict[str, LocaleCopy]


class CopyManifest(BaseModel):
    variants: list[VariantCopy]


class GenerationTarget(BaseModel):
    product_id: str
    model_id: str
    variant_id: str
    asset_png: str
    aspect_ratio: str
    locale_id: Optional[str] = None
    stage1_prompt: str
    stage2_prompt: str


class RenderJob(BaseModel):
    job_id: str
    locale: str
    product_id: str
    model_id: str
    variant_id: str
    asset_name: str
    aspect_ratio: str
    stage1_model: str
    stage2_model: str
    generation_index: int
    bg_video_path: str
    logo_path: str
    tagline: str
    product_name: str
    cta: str
    composition_name: str
    output_filename: str
    output_path: str
