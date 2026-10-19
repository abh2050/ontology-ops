# Higgsfield visual treatment — research and implementation

Research date: 2026-10-19. Scope: presentation media for the existing case-study website, not a new image-generation application or a product feature.

## What the research supports

1. **Create a coherent still before animating it.** Higgsfield's image API accepts an explicit prompt, aspect ratio and resolution. A controlled composition establishes the site's white, ice-blue, cobalt and navy palette before image-to-video adds movement. [Official image API reference](https://open.higgsfield.ai/models/marketing-studio/image/api-reference). Higgsfield also describes directing the camera and pacing when animating an illustration; this treatment deliberately keeps the camera stationary. [Creative workflow reference](https://higgsfield.ai/image-to-video-ai).
2. **Keep motion narrow and purposeful.** The selected image-to-video operation supports a source image, ending image, duration and sound control. The art brief uses a locked camera and gentle movement along the existing connections, with the same start/end image requested. This is conceptual illustration, not a rendered architecture or UI. [Official image-to-video reference](https://open.higgsfield.ai/models/kling-video/v3.0/std/image-to-video/api-reference).
3. **Generate at build time, serve frozen local files.** Higgsfield credentials belong in a server-side or one-shot build process, not browser code. The published page needs only the resulting poster and MP4. It makes no Higgsfield requests. [Official API quick start and credential guidance](https://open.higgsfield.ai/quick-start).
4. **Prefer an optimized video over an animated GIF.** Local H.264, removed audio, a compressed WebP poster, and deferred source attachment keep the animation bounded. A poster preserves the design while the video is unavailable or not requested. [web.dev: Video performance](https://web.dev/learn/performance/video-performance).
5. **Give the visitor control.** Looping motion has an explicit pause/play button. Reduced-motion and data-saving preferences use the still by default. Leaving the viewport or hiding the tab pauses playback. Without JavaScript, the illustration remains visible. [web.dev: Audio and video considerations](https://web.dev/learn/html/audio-video).

## Applied visual concept

Separate parcels and order records connect through a shared seller/fulfillment hub into one investigation folder. The purpose is to make the business idea recognizable before a visitor reaches the real application walkthrough. There are no invented product screens, metrics, AWS symbols or delay-cause assertions in the generated artwork.

The existing business story, three real UI captures, source-backed architecture and benchmark results remain unchanged. The hero identifies the media as conceptual Higgsfield-generated art and links directly to the actual product section.

## Generation and cost boundary

One image request (`99c418b9-6f75-4368-8385-dd0a85167c6d`) and one five-second animation request (`8ac371a8-41a0-4b5e-9f2a-481a5d86311c`) completed successfully. The conservative pre-run budget was below $1.50 based on the published standard rate ranges. Actual billed cost was not independently checked. No automatic regeneration or paid retry loop was used.

Pricing references: [image rates](https://open.higgsfield.ai/models/marketing-studio/image/playground) and [animation rates](https://open.higgsfield.ai/models/kling-video/v3.0/std/image-to-video/playground). Rates are time-sensitive; the budget is not an invoice.

Original generated files are local under `.local/case-study/hero-media/`. `scripts/build_case_study_assets.mjs` derives the optimized public media from available originals and performs no paid calls. Credentials and provider result URLs are not included in public assets.

## Verification

The delivered MP4 is 133,946 bytes, 1080 × 716, H.264, approximately 5.04 seconds, with no audio stream. The 1440 × 960 WebP poster is 58,228 bytes. Early/middle/late video frames and desktop/mobile page captures were visually inspected.

The full case-study browser check passed at 320, 390, 768, 1024 and 1440 pixels. It also checked muted playback, pause/play controls, automatic offscreen pause/resume, retained user pause intent, changes to reduced-motion preference, simulated video-error fallback, a data-saving still without an attached video source, and no-JavaScript poster availability. The reduced-motion page made zero video requests. All existing product tabs, technical interactions and model-comparison cells passed, with zero API requests or page errors. This verifies presentation behavior, not a new product benchmark or cloud deployment.
