# Case-study visual assets

- `graph.webp`, `review.webp`: optimized captures of the implemented static sandbox. Authored fixtures only; all actions simulated. Originals and capture verification are in the separate local demo workspace `brag-output-2026-10-19-134102/`. No live model or deployment claim is attached to these images.
- `cloudfront.svg`, `fargate.svg`, `rds.svg`, `sqs.svg`, `bedrock.svg`: official `mxgraph.aws4` resource symbols extracted from the existing `docs/diagrams/aws-deployment.svg` export using its matching editable draw.io cells. They are not AI-generated architecture symbols.
- `higgsfield-illustration.webp`: abstract conceptual artwork generated through the Higgsfield API on 2026-10-19. Request `f0489e32-050c-4853-9ff4-5ef206996bbb` completed successfully. It contains no source data and depicts neither the deployed architecture nor an actual product result. One image was submitted; actual billing was not independently checked. The high-resolution original is retained locally under `.local/case-study/`.
- `social.svg`, `social.png`, `favicon.svg`: local vector identity and social preview, based on the page typography and colors.

`scripts/build_case_study_assets.mjs` extracts symbols, optimizes available local captures, and renders the social preview. It performs no paid generation and contains no credentials. It requires the original local demo captures, the retained illustration for illustration regeneration, Playwright dependencies from `frontend/`, and a local static server at `CASE_STUDY_BASE`.
