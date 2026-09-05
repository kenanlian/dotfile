---
name: kenan-ui-ux-design
description: Use Kenan's clean, native, light-first UI taste.
version: 0.1.0
author: 柯楠, Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [design, ui, ux, web-design, product-design]
    related_skills: []
---

# Kenan UI/UX Design Skill

Apply 柯楠’s established product-design taste when discussing, specifying, building, or reviewing websites and application interfaces. Treat this as a default design direction, not an inflexible theme: product semantics and usability remain decisive.

## When to Use

Use this skill when:

- Discussing the visual direction of a product, website, landing page, desktop app, plugin, or workspace UI.
- Writing UI/UX requirements, design briefs, implementation prompts, or acceptance criteria.
- Comparing design variants or reviewing an implemented interface.
- Choosing colors, typography, spacing, surfaces, borders, radius, motion, or content structure.
- Deciding whether a hard engineering aesthetic fits the product.

Do not apply it mechanically when:

- 柯楠 explicitly requests a different visual language.
- The task requires faithful reproduction of another brand or design system.
- Domain conventions or accessibility requirements conflict with an aesthetic preference.

## Design Thesis

The primary direction is **clean, native, softly tactile tool minimalism**, with Otty as the strongest reference.

The page or application should feel:

- Light-first, calm, and precise.
- Clean rather than visibly over-structured.
- Native and product-led rather than template-led.
- Spacious at a distance, useful and detailed up close.
- Softly tactile at interaction points, not soft everywhere.
- Technically credible without defaulting to cyberpunk styling.

A compact summary:

> Clean over exposed structure. Texture over decoration. Roundness for interaction. Engineering character only when justified.

## Reference Hierarchy

Use references by role rather than copying them wholesale:

1. **Otty — primary reference**
   - Clean native-tool minimalism.
   - Large breathing room and restrained product presentation.
   - Few explicit borders; hierarchy comes from spacing, alignment, and tonal surfaces.
   - Rounded small controls and refined, quiet microinteractions.
   - Concise product story and moderate landing-page length.

2. **Pi — optional editorial accent**
   - Warm paper-like surfaces, distinctive typography, and restrained technical texture.
   - Borrow selectively; visible grids, retro terminal motifs, and hard edges are not defaults.

3. **Zed — conditional engineering mode**
   - Appropriate when the product must strongly communicate precision, infrastructure, debugging, code, or engineering rigor.
   - Use for dense workspaces, advanced settings, developer modes, structural diagrams, and technical views.
   - Do not make it the default brand shell for a softer general productivity product.

4. **VMark — useful contrast**
   - Its approachable functionality is valid, but repeated cards, borders, tabs, and demo containers can become visually noisy.
   - Prefer Otty’s open grouping and quieter shell when both approaches are possible.

5. **omp — visual inspiration only**
   - Typography contrast, restrained brand color, and technical labels can inspire details.
   - Do not default to its extremely long page or exhaustive feature-by-feature narrative.

## Light and Dark Modes

Use a **light-first, not light-only** strategy:

- The primary brand, marketing page, and default visual presentation should normally be light.
- Use warm white, paper white, or quiet gray rather than clinical white when appropriate.
- A polished dark design is welcome as a secondary mode for night use, immersive workspaces, editors, terminals, or media-heavy views.
- Do not create dark mode by mechanically inverting light tokens.
- A light product shell may contain a dark editor or terminal screenshot.
- Avoid equating “developer product” with black backgrounds, neon glows, and saturated gradients.

## Hierarchy: Proximity Before Enclosure

Prefer grouping by **proximity, alignment, whitespace, and tonal contrast** before drawing containers.

Use this order when separating elements:

1. Spacing and proximity.
2. Alignment and shared grid position.
3. Typography and emphasis.
4. Background or gray-level difference.
5. A subtle divider.
6. A complete border or card only when the previous methods are insufficient.

The goal is not “no borders.” The goal is to make most boundaries implicit.

### Border Budget

Before adding a border, ask what ambiguity it resolves.

- Keep a border when it clarifies interaction, selection, focus, resizing, drag boundaries, tabular structure, or dense technical data.
- Remove a border that merely repeats grouping already expressed by spacing or background.
- Avoid nested bordered cards.
- Avoid giving every feature, paragraph, and control its own rectangle.
- Prefer hairlines and low-contrast dividers over dark outlines.

## Surfaces and Cards

- Keep the main canvas visually quiet.
- Build hierarchy with neighboring light tones instead of dramatic elevation.
- Cards should be used for real object identity or interaction, not as the automatic layout primitive.
- Prefer embedded surfaces over floating surfaces.
- Avoid glassmorphism and stacked translucent panels unless the product semantics genuinely require them.
- Shadows should be rare, soft, and used mainly for movable layers, menus, dialogs, screenshots, or application windows.

## Color Direction

Default palette behavior:

- Warm white, neutral white, or very light gray canvas.
- Near-black primary text, not absolute black everywhere.
- Muted gray secondary text.
- One cool identifying accent such as gray-blue, cobalt, or soft cyan.
- One optional warm or magenta accent for a special state or brand moment.
- Saturated colors should mark action, status, selection, code semantics, or a single memorable brand element.
- Avoid large decorative gradient fields and many unrelated accent colors.

Do not treat these as fixed hex values. Derive accessible tokens for the actual product and verify contrast.

## Typography

Use typography to create identity without visual clutter:

- Use a neutral humanist sans or system-like face for core UI and body copy.
- Use monospace selectively for commands, shortcuts, versions, code, parameters, and metadata.
- A distinctive serif, italic, or display face may be used for editorial or brand moments, but is optional.
- Prefer a small number of clear roles over many unrelated typefaces.
- Use moderate weight contrast; do not rely on ultra-bold oversized sans headings as the only identity.
- Keep technical microcopy compact and readable rather than merely decorative.

The stable preference is **role-based type contrast**, not mandatory serif typography.

## Radius and Tactility

Roundness should communicate touch and interaction:

- Small buttons, toggles, filters, status tags, segmented controls, and compact actions may be rounded or pill-shaped.
- Product windows and major media may use a softer medium radius.
- Static content regions and large layout containers should usually remain open or use modest radius.
- Avoid applying the same large radius to every panel.
- Avoid bubble-like layouts where all information becomes a soft capsule.

A useful default scale:

- Dense technical objects: 2–4px.
- Standard controls and compact surfaces: 6–8px.
- Large application windows or media: 10–14px.
- Pills: only for semantically compact interactive objects.

Adjust these values to the platform and component scale rather than treating them as hard tokens.

## Microinteractions

Microinteractions should feel **short, light, precise, and tactile**:

- Prefer small color, opacity, elevation, or compression changes.
- Keep travel distance short.
- Use ease-out motion for direct feedback and avoid elastic spectacle by default.
- Let tabs and selections move smoothly without drawing attention away from content.
- Use animation to explain state, progress, spatial relationships, or product behavior.
- Return the interface to a quiet resting state after the interaction.
- Respect reduced-motion preferences.

Avoid continuous floating, glowing, rotating, cursor-chasing, or decorative motion that does not improve understanding.

## Product Presentation

The real product should carry the visual story:

- Show real, readable UI, not generic 3D illustrations or abstract “AI magic.”
- Use screenshots, short demonstrations, commands, shortcuts, states, and workflows as evidence.
- Keep the surrounding website quieter than the product being presented.
- Crop screenshots deliberately and preserve enough detail to feel credible.
- Introduce the product early; do not make users scroll through a manifesto before seeing it.

## Landing-Page Length and Structure

Prefer a concise, deliberate product page over exhaustive documentation.

Default structure:

1. Hero: one clear positioning statement, primary action, optional secondary action, and product evidence.
2. Core value: three to five capabilities with short mechanism-oriented explanations.
3. One or two real workflows or interaction demonstrations.
4. Necessary technical, compatibility, privacy, or trust information.
5. Final download, trial, or start action.

Stop when the product is understood. Move exhaustive feature catalogs, technical details, and edge cases into documentation.

Each section should answer a distinct user question. Remove sections that repeat the same claim with different decoration.

## Choosing the Engineering Intensity

Before using visible grids, hard borders, dense monospace labels, blueprint motifs, or Zed-like precision, classify the product:

### Use low engineering intensity by default

Appropriate for writing tools, personal productivity, creative software, knowledge work, consumer-facing utilities, and general workspaces.

- Open layout.
- Quiet tonal grouping.
- Soft interactive controls.
- Sparse technical decoration.

### Use high engineering intensity deliberately

Appropriate for editors, debuggers, infrastructure, developer tools, data systems, advanced workspaces, and modes where precision itself is a product promise.

- More explicit grid and alignment.
- Denser labels and state information.
- Smaller radius and stronger dividers.
- Monospace and technical notation may carry more visual weight.

Do not use high engineering intensity merely to make a product look sophisticated.

## UX Behavior

Aesthetic preferences do not override usability:

- Keep the primary action unmistakable.
- Preserve visible focus states even in low-border designs.
- Use progressive disclosure for advanced capability.
- Make keyboard support discoverable when it matters.
- Use concise labels and mechanism-oriented explanations rather than vague marketing language.
- Ensure empty, loading, error, disabled, hover, focus, selected, and destructive states remain distinguishable.
- Keep touch targets and text contrast accessible.

## Design Procedure

1. **Identify product character.** State the product category, users, core action, desired emotional qualities, and whether precision is itself a selling point. Completion criterion: the engineering intensity is explicitly classified as low, medium, or high.
2. **Choose a reference mix.** Start with Otty as the default; add Pi, Zed, VMark, or omp only for a named purpose. Completion criterion: every borrowed reference has a specific role rather than a vague “looks like” request.
3. **Design the hierarchy without cards.** Lay out content using spacing, alignment, typography, and tonal surfaces first. Completion criterion: every remaining border or card resolves a concrete ambiguity.
4. **Assign interaction tactility.** Decide which objects deserve radius, hover feedback, pressed feedback, selection, or motion. Completion criterion: roundness and motion map to interactive semantics.
5. **Control content length.** Define the minimum sections needed to understand and trust the product. Completion criterion: repeated claims and documentation-level detail are removed or linked out.
6. **Specify light and dark roles.** Design light as primary and dark as a considered secondary mode where useful. Completion criterion: dark tokens and states are designed, not inverted.
7. **Verify in the real interface.** Exercise key flows in the browser or application at representative desktop and narrow widths. Completion criterion: hierarchy, states, focus, responsiveness, and motion are observed in the running product.

## Review Checklist

### Visual cleanliness

- [ ] Grouping uses proximity and tone before complete borders.
- [ ] No unnecessary nested cards.
- [ ] The page shell is quieter than the product content.
- [ ] Every accent color has a functional or branding role.
- [ ] Shadows appear only where elevation is meaningful.

### Interaction quality

- [ ] Rounded objects correspond to touchable or movable semantics.
- [ ] Hover, focus, pressed, selected, disabled, and destructive states are distinct.
- [ ] Motion is short, informative, and reduced-motion safe.
- [ ] Low-border styling has not weakened focus visibility or accessibility.

### Product communication

- [ ] The real product appears early.
- [ ] The primary action is obvious.
- [ ] The page explains three to five core capabilities without becoming documentation.
- [ ] Technical proof is concrete rather than decorative.
- [ ] The page ends when the product is understood.

### Style fit

- [ ] Light is the primary direction; dark is a deliberate secondary option.
- [ ] Zed-like engineering intensity is justified by product semantics.
- [ ] Otty-like cleanliness remains the default when no stronger reason exists.

## Pitfalls

- **Borderless ambiguity:** Removing borders without improving spacing, tone, or focus states makes the interface vague rather than clean.
- **Card reflex:** Wrapping every block in a card reproduces generic SaaS visual noise.
- **Softness everywhere:** Repeating pills and large radii removes hierarchy and makes a professional tool feel toy-like.
- **False engineering:** Grids, tiny monospace labels, and blueprint marks become decoration when they do not express real structure.
- **Empty minimalism:** Large whitespace without product evidence or action is not the desired style.
- **Documentation homepage:** Exhaustive feature coverage weakens narrative focus; link to documentation instead.
- **Mechanical dark mode:** Simple inversion usually damages hierarchy, saturation, shadows, and semantic states.
- **Invisible accessibility:** A low-border aesthetic must still retain strong keyboard focus, error, selection, and destructive-state visibility.

## Verification

Before approving a design or implementation:

1. Inspect the running interface rather than relying only on mockups or code.
2. Exercise the primary user flow and all visible control states.
3. Check representative desktop and narrow layouts.
4. Verify keyboard focus, contrast, reduced motion, and readable product screenshots.
5. Explain every border, card, shadow, accent, and animation; remove those without a clear role.
6. Confirm the final result feels clean first, tactile second, and technical only to the degree justified by the product.
