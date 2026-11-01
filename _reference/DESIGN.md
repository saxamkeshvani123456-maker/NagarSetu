---
name: CivicLens
colors:
  surface: '#fff8f0'
  surface-dim: '#ecd9a7'
  surface-bright: '#fff8f0'
  surface-container-lowest: '#ffffff'
  surface-container-low: '#fff2d8'
  surface-container: '#ffecbe'
  surface-container-high: '#fbe7b4'
  surface-container-highest: '#f5e1af'
  on-surface: '#231a00'
  on-surface-variant: '#51434a'
  inverse-surface: '#3a2f0c'
  inverse-on-surface: '#fff0cb'
  outline: '#83737a'
  outline-variant: '#d6c1c9'
  surface-tint: '#8f4572'
  primary: '#450432'
  on-primary: '#ffffff'
  primary-container: '#601d49'
  on-primary-container: '#db85b6'
  inverse-primary: '#ffaeda'
  secondary: '#9d3c5f'
  on-secondary: '#ffffff'
  secondary-container: '#fe89af'
  on-secondary-container: '#781e42'
  tertiary: '#411215'
  on-tertiary: '#ffffff'
  tertiary-container: '#5c2729'
  on-tertiary-container: '#d78d8d'
  error: '#ba1a1a'
  on-error: '#ffffff'
  error-container: '#ffdad6'
  on-error-container: '#93000a'
  primary-fixed: '#ffd8ea'
  primary-fixed-dim: '#ffaeda'
  on-primary-fixed: '#3c002b'
  on-primary-fixed-variant: '#732d59'
  secondary-fixed: '#ffd9e2'
  secondary-fixed-dim: '#ffb1c7'
  on-secondary-fixed: '#3f001c'
  on-secondary-fixed-variant: '#7f2448'
  tertiary-fixed: '#ffdad9'
  tertiary-fixed-dim: '#ffb3b3'
  on-tertiary-fixed: '#380b0f'
  on-tertiary-fixed-variant: '#6e3637'
  background: '#fff8f0'
  on-background: '#231a00'
  surface-variant: '#f5e1af'
typography:
  display-lg:
    fontFamily: Playfair Display
    fontSize: 48px
    fontWeight: '700'
    lineHeight: 56px
    letterSpacing: -0.02em
  headline-lg:
    fontFamily: Playfair Display
    fontSize: 32px
    fontWeight: '700'
    lineHeight: 40px
  headline-lg-mobile:
    fontFamily: Playfair Display
    fontSize: 28px
    fontWeight: '700'
    lineHeight: 36px
  headline-md:
    fontFamily: Playfair Display
    fontSize: 24px
    fontWeight: '600'
    lineHeight: 32px
  body-lg:
    fontFamily: Inter
    fontSize: 18px
    fontWeight: '400'
    lineHeight: 28px
  body-md:
    fontFamily: Inter
    fontSize: 16px
    fontWeight: '400'
    lineHeight: 24px
  label-md:
    fontFamily: Inter
    fontSize: 14px
    fontWeight: '600'
    lineHeight: 20px
    letterSpacing: 0.01em
  label-sm:
    fontFamily: Inter
    fontSize: 12px
    fontWeight: '500'
    lineHeight: 16px
    letterSpacing: 0.04em
rounded:
  sm: 0.25rem
  DEFAULT: 0.5rem
  md: 0.75rem
  lg: 1rem
  xl: 1.5rem
  full: 9999px
spacing:
  unit: 8px
  container-margin: 20px
  gutter: 16px
  stack-sm: 8px
  stack-md: 16px
  stack-lg: 32px
---

## Brand & Style
The design system for this product is rooted in an **Editorial Humanist** aesthetic. It moves away from the cold, clinical feel of typical government or utility apps, instead embracing the warmth and authority of a high-end magazine or a trusted community journal. The goal is to make civic engagement feel like a dignified, community-focused conversation rather than a bureaucratic chore.

The visual style blends **Minimalism** with **Tactile/Paper-like** qualities. Large, elegant serif headlines provide an authoritative yet welcoming "voice," while a warm cream background reduces digital eye strain and creates a sense of physical permanence. The interface prioritizes clarity, high-quality whitespace, and a sophisticated color palette to evoke feelings of trust, safety, and empowerment among citizens.

## Colors
The palette is designed to be warm and sophisticated, centered around "Deep Plum" for clarity and authority.

- **Primary (#601D49):** Used for high-level information hierarchy, including headers, primary navigation icons, and the most critical call-to-action buttons.
- **Secondary (#BD5579):** Applied to interactive elements like links, toggles, and active navigation states to provide a clear but soft visual cue.
- **Tertiary (#EA9D9D):** Reserved for decorative accents, subtle badge backgrounds, and supporting illustrations.
- **Surface/Neutral (#FFEBB8):** The foundational background color. It provides a warm, paper-like texture that distinguishes the app from standard white-label digital products.

**Accessibility Note:** All body copy and critical UI labels must use the Primary Deep Plum color when placed on the Neutral or Tertiary backgrounds to maintain WCAG AA contrast ratios.

## Typography
The typography system employs a "Serif-to-Sans" handoff. 

- **Headlines:** Use **Playfair Display**. This font carries the editorial weight of the brand. It should be used for page titles, section headers, and the app branding. 
- **Body & UI:** Use **Inter**. This provides a functional, highly readable contrast to the expressive headlines. It is used for all descriptive text, form inputs, and button labels.

For mobile devices, headlines scale down slightly to ensure word-wrapping remains graceful and avoids excessive hyphenation. High-contrast pairings (Plum text on Cream background) are mandatory for all body-scale text.

## Layout & Spacing
The design system utilizes a **Fluid Grid** model based on an 8px base unit.

- **Mobile:** 4-column grid with 20px outside margins and 16px gutters.
- **Tablet/Desktop:** 12-column centered grid with a maximum content width of 1140px.

Layouts should feel spacious and intentional. Use "stack" spacing to group related information (8px for related items within a card, 32px between major sections). The "Editorial" feel is achieved by allowing generous vertical margins around headlines, giving the content room to "breathe" on the warm cream background.

## Elevation & Depth
This design system uses **Tonal Layers** and **Ambient Shadows** to create a soft, non-aggressive sense of depth.

- **Flat Base:** The main background is always the warm neutral cream (#FFEBB8).
- **Raised Surfaces:** Cards and containers use a slightly lighter tint of the neutral color or white, paired with a very soft, diffused shadow.
- **Shadow Profile:** Shadows should be long and low-opacity (Blur: 20px, Y-Offset: 4px, Opacity: 8%), using a tinted plum color rather than pure black to keep the warmth of the UI intact.
- **Interactive Depth:** On press/active states, elements should appear to slightly "sink" by reducing shadow blur, providing tactile feedback to the user.

## Shapes
The shape language is defined as **Rounded**, reinforcing the approachable and human tone of the brand.

- **Standard Elements (Buttons, Inputs, Small Cards):** Use 0.5rem (8px) corner radius.
- **Large Containers (Feature Cards, Modals):** Use 1rem (16px) corner radius.
- **Decorative Elements (Badges, Tags):** Can use the "Pill-shaped" 3.0 scale for a friendlier, softer appearance.

Avoid sharp 0px corners, as they conflict with the "warm and trustworthy" brand personality.

## Components
Consistent implementation of components ensures the editorial feel remains functional:

- **Buttons:** 
  - *Primary:* Deep Plum background with Cream text. Heavyweight, rounded corners.
  - *Secondary:* Rose outline with Deep Plum text.
- **Cards:** Subtle white or light-cream background, soft ambient shadow, and generous internal padding (24px).
- **Input Fields:** Thick 2px border in a low-opacity Deep Plum. Label text is always in Inter Bold (label-md).
- **Chips/Badges:** Pill-shaped, using the Soft Coral (#EA9D9D) for status highlights or category tags.
- **Lists:** Separated by thin, low-contrast plum dividers (10% opacity) to maintain order without cluttering the editorial flow.
- **Skeleton States:** Use a pulsing animation between the Cream background and the Soft Coral color to keep the transition warm during AI processing or data loading.
- **Illustrations:** Should be organic, hand-drawn styles using the defined Plum and Rose palette to emphasize the human-centric nature of the app.