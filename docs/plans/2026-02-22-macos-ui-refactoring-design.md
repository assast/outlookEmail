# macOS UI Refactoring Design

## 1. Overview
The goal of this refactoring is to deeply transform the frontend UI (`templates/index.html`) into a pure macOS/Apple Mail aesthetic. While the current implementation has a good foundational structure (fonts, blur effects, layout), it relies heavily on emojis for icons, uses web-style active states (left border highlights), and contains scattered inline styles. This refactoring will address these issues to deliver a native-feeling experience.

## 2. Dependencies
- **Lucide Icons**: We will introduce `lucide.min.js` via CDN to replace all emojis with high-quality, lightweight SVG line icons that closely resemble Apple's SF Symbols.

## 3. UI & Interaction Changes
- **Iconography**: 
  - Remove all emoji characters (`📁`, `📬`, `⚙️`, `🗑️`, `🔍`, etc.).
  - Replace with `<i data-lucide="icon-name"></i>`.
  - Add `lucide.createIcons()` initialization in the main script.
- **Active/Selected States**: 
  - Refactor `.account-item.active`, `.group-item.active`, and `.email-item.active`.
  - Remove the left border highlight.
  - Apply a full row highlight with the primary macOS blue (`#007AFF`).
  - Invert text and icon colors to pure white (`#ffffff`) when active.
- **Focus Rings**: 
  - Update `box-shadow` on input, textarea, and select elements during `:focus` to use the standard, softer macOS blue glow, removing any harsh web-style borders.
- **Buttons**:
  - Refactor the GitHub Star button to remove the linear gradient, adopting a standard macOS toolbar ghost/bordered button style.
  - Unify button hover/active states with slight scaling (`transform: scale(0.98)`) for a native, physical feel.

## 4. Code Structure & Cleanup
- **Inline Styles**: 
  - Scan `index.html` for `style="..."` attributes (specifically in sorting controls, batch action bars, and tag filters).
  - Extract these into semantic CSS classes within the `<style>` block.
- **DOM Consistency**: Ensure all dynamic DOM generation in JavaScript (e.g., rendering account lists or emails) applies the new Lucide icon tags instead of emojis.

## 5. Success Criteria
- The UI contains zero emojis used as UI icons.
- All inline styles in the main layout sections are extracted to CSS classes.
- The visual presentation looks and feels like a native macOS application.