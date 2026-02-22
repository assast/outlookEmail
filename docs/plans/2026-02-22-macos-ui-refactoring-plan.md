# macOS UI Refactoring Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Transform the frontend UI into a pure macOS/Apple Mail aesthetic by replacing emojis with SVG icons, refining interaction states, and cleaning up inline styles.

**Architecture:** We will modify the single-page application template `templates/index.html`. We will inject Lucide icons via CDN, extract inline CSS into the `<style>` block, and update JS rendering functions to output icon tags instead of emojis.

**Tech Stack:** HTML5, CSS3, Vanilla JavaScript, Lucide Icons (CDN).

---

### Task 1: Setup Lucide Icons and Global CSS Variables

**Files:**
- Modify: `templates/index.html` (Head section and global styles)

**Step 1: Inject Lucide CDN and initialize script**
Add the Lucide script tag to `<head>` and the initialization call at the bottom of the `<body>` (or inside DOMContentLoaded).

**Step 2: Define macOS CSS constants**
Extract hardcoded macOS colors into CSS variables in `:root` (e.g., `--mac-blue: #007AFF;`, `--mac-red: #FF3B30;`) for consistency.

**Step 3: Test and verify**
Run the Flask server and ensure `lucide.min.js` loads without console errors.

**Step 4: Commit**
```bash
git add templates/index.html
git commit -m "chore(ui): add Lucide icons dependency and CSS variables"
```

---

### Task 2: Refactor CSS Interaction States and Focus Rings

**Files:**
- Modify: `templates/index.html` (`<style>` block)

**Step 1: Update active states**
Modify `.account-item.active`, `.group-item.active`, and `.email-item.active` to remove `border-left` and apply a solid `--mac-blue` background with white text and icons.

**Step 2: Update focus rings**
Modify `.form-input:focus`, `.form-textarea:focus`, and `.search-input:focus` to use a softer macOS glow (e.g., `box-shadow: 0 0 0 3px rgba(0, 122, 255, 0.25); border-color: var(--mac-blue);`).

**Step 3: Update GitHub button and general button states**
Remove the gradient from `.github-star-btn`. Add `&:active { transform: scale(0.98); }` to `.btn`, `.navbar-btn`, and list items for native tactile feedback.

**Step 4: Test and verify**
Click through items and inputs in the UI to verify the visual changes feel native.

**Step 5: Commit**
```bash
git add templates/index.html
git commit -m "style(ui): update active states, focus rings, and button interactions to macOS standard"
```

---

### Task 3: Extract Inline Styles to CSS Classes

**Files:**
- Modify: `templates/index.html` (HTML structure and `<style>` block)

**Step 1: Extract Sorting Control styles**
Move the inline styles from the `.sort-control` div and its buttons to classes like `.sort-bar`, `.sort-button`.

**Step 2: Extract Batch Action Bar styles**
Move inline styles from `#batchActionBar` and `#emailBatchActionBar` to a new `.batch-action-bar` class.

**Step 3: Extract Tag Filter styles**
Move inline styles from `#tagFilterContainer` to a `.tag-filter-bar` class.

**Step 4: Test and verify**
Ensure the layout remains exactly the same after removing the inline `style=""` attributes.

**Step 5: Commit**
```bash
git add templates/index.html
git commit -m "style(ui): extract inline CSS to semantic classes"
```

---

### Task 4: Replace Static Emojis with Lucide Icons (HTML)

**Files:**
- Modify: `templates/index.html` (Static HTML content)

**Step 1: Update Navbar and Empty States**
Replace ⚙️ with `<i data-lucide="settings"></i>` in navbar.
Replace 📁, 📬, 📄 in `.empty-state` with `<i data-lucide="folder-open"></i>`, `<i data-lucide="inbox"></i>`, `<i data-lucide="file-text"></i>`.

**Step 2: Update Panel Headers and Toolbars**
Replace `+` with `<i data-lucide="plus"></i>`.
Replace 🏷️ with `<i data-lucide="tag"></i>`.
Replace 🗑️ with `<i data-lucide="trash-2"></i>`.
Replace 🔍 with `<i data-lucide="search"></i>`.
Replace 📨 with `<i data-lucide="mail"></i>`.
Replace ⚠️ with `<i data-lucide="alert-triangle"></i>`.

**Step 3: Test and verify**
Reload the page and ensure all static emojis are now rendering as sleek Lucide SVG icons.

**Step 4: Commit**
```bash
git add templates/index.html
git commit -m "feat(ui): replace static emojis with Lucide SVG icons"
```

---

### Task 5: Replace Dynamic Emojis in JavaScript Renders

**Files:**
- Modify: `templates/index.html` (`<script>` block)

**Step 1: Update JS rendering templates**
Search the JavaScript code for emojis used in template literals (e.g., inside `renderAccounts()`, `renderEmails()`, `renderGroups()`).
Replace them with `<i data-lucide="..."></i>` tags. *Crucial: Call `lucide.createIcons()` after updating the DOM in these functions so the new icons render.*

**Step 2: Test and verify**
Add a new account, fetch emails, and verify that dynamically injected content displays SVG icons instead of emojis.

**Step 3: Commit**
```bash
git add templates/index.html
git commit -m "feat(ui): replace dynamic emojis with Lucide icons in JS renders"
```
