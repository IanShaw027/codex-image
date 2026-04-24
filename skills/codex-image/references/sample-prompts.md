# Sample prompts

Use these as starting points. They are intentionally more complete than the average user prompt.

## Generate

### Doraemon-inspired large model infographic

```text
Use case: illustration-story
Asset type: 4K wallpaper
Primary request: a Doraemon-inspired large language model illustration, image only, no text
Scene/backdrop: bright futuristic AI lab with floating tokens, context windows, tool icons, embeddings, and glowing transformer diagrams
Subject: a cute blue robot-cat-inspired AI mascot opening a dimensional pocket that releases language tokens and reasoning paths
Style/medium: premium anime illustration, crisp line art, polished cel shading
Composition/framing: cinematic 16:9 hero composition, centered subject, strong depth, wallpaper-friendly
Lighting/mood: luminous, optimistic, playful, futuristic
Color palette: cyan blue, white, red accents, yellow highlight, teal holographic glow
Materials/textures: glossy robot shell, soft fabric pocket, translucent holograms, smooth metallic lab surfaces
Constraints: no text, no watermark, no logo, no extra characters
Avoid: blurry details, distorted face, extra limbs, horror vibe, dark gritty scene
```

### Clean AI wallpaper

```text
Use case: stylized-concept
Asset type: desktop wallpaper
Primary request: clean futuristic AI wallpaper with floating geometric light structures
Style/medium: premium digital illustration
Composition/framing: wide 16:9 layout with balanced negative space
Lighting/mood: bright, calm, high-tech
Constraints: no text, no watermark
```

### Product poster

```text
Use case: product-mockup
Asset type: poster
Primary request: premium poster of a transparent glass bottle with a silver cap
Scene/backdrop: clean studio gradient from pale gray to white
Style/medium: high-end product photography
Composition/framing: centered object, generous margins
Lighting/mood: soft controlled highlights, subtle reflection
Constraints: no logos, no watermark
```

## Edit

### Multi-reference product poster

```text
Use case: product-mockup
Asset type: commercial promotional poster
Input image 1 role: person reference; preserve the recognizable styling, pose direction, clothing, and overall personality cues.
Input image 2 role: handbag product reference; preserve the bag shape, color, handles, strap detail, tag, and material feel.
Primary request: create a polished advertising image showing the person from input image 1 holding the handbag from input image 2.
Scene/backdrop: clean studio background with soft gradient and subtle shadow, premium fashion e-commerce campaign atmosphere
Style/medium: photorealistic commercial fashion ad, crisp product lighting, high-end catalog polish
Composition/framing: wide 16:9 layout, person slightly left of center, bag clearly visible in the foreground, negative space on the right for future copy, no actual text
Constraints: tasteful and non-explicit; no logos, no readable text, no watermark; keep the product close to input image 2 and the person styling close to input image 1
```

### Background-only edit

```text
Use case: precise-object-edit
Asset type: poster revision
Primary request: replace only the background with a bright blue futuristic scene
Constraints: change only the background; keep the subject, silhouette, pose, and proportions unchanged; no text; no watermark
Avoid: extra props, style drift, altered face
```

### Multi-turn realism follow-up with one new attachment

Command shape:

```bash
python3 "$CODEX_IMAGE" edit \
  --image '[Turn -1 Image #1]' \
  --image '[Turn -1 Image #2]' \
  --image '[Image #1]' \
  "Use the second image as the base composition and pose. Replace the subject with the person from the first image. Use the new current-turn image only as a realism and skin-texture reference. Keep the base framing, wardrobe, lighting, hand pose, body angle, and background from image 2, while preserving the identity and recognizable facial structure from image 1."
```

Why this shape:

- Previous turn image 1: person identity reference
- Previous turn image 2: target base scene
- Current turn image 1: new realism reference
- Do not rewrite this as `[Image #1]`, `[Image #2]`, `[Image #3]` after only one new upload

### Refine the previous result image

Command shape:

```bash
python3 "$CODEX_IMAGE" edit \
  --image-set last-output \
  --image '[Image #1]' \
  "Use the previous saved result image as the base to refine. Keep its overall composition and subject placement, but use the new current-turn image only as a realism reference for face detail, skin texture, and lighting cleanup."
```

Why this shape:

- `last-output`: the previous generated result image you want to keep refining
- Current turn image 1: new correction or realism reference
- In the prompt, explicitly say the last output is the base result to refine, and the new image is only a supporting reference

### Text cleanup

```text
Use case: text-localization
Asset type: infographic revision
Primary request: replace the existing title text with "LARGE MODEL FLOW"
Constraints: preserve layout, hierarchy, spacing, and typography style; no extra text
```
