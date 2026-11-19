# YouTube Studio Batch Scheduler ⚡

An Apple & Vercel-inspired batch upload time picker designed for YouTube creators publishing long-form videos and Shorts. Built adhering to the design engineering guidelines of **[emilkowalski/skills](https://github.com/emilkowalski/skills)** and **[vercel-labs/agent-skills](https://github.com/vercel-labs/agent-skills)**.

![OLED Dark Mode](https://img.shields.io/badge/Theme-OLED%20Dark-black?style=flat-square)
![15-Min Grid](https://img.shields.io/badge/Intervals-15--Minute%20Grid-0070F3?style=flat-square)
![Vercel Ready](https://img.shields.io/badge/Deploy-Vercel-black?style=flat-square&logo=vercel)

---

## Features

- **Strict 15-Minute Grid**: All generated times end in `:00`, `:15`, `:30`, or `:45` for native compatibility with YouTube Studio's scheduler dropdown.
- **Video First → Shorts Second**: Automatically enforces upload release sequence:
  - `1️⃣ Video (Upload First)` publishes during high-velocity windows.
  - `2️⃣ Short (Upload After)` drops after the long video is already indexing to drive instant watch velocity.
- **Automatic US Date Rollover (+1 Day)**:
  - Targeting American viewers (2:00–4:00 PM EST) from India (IST) requires scheduling between `12:30 AM – 2:30 AM IST`.
  - The app automatically calculates and flags the **Next-Day Date** (+1 Day badge) so you never schedule on the wrong date in YouTube Studio.
- **iPhone Wheel Drum Animation**:
  - Physics-based rolling reels with cylindrical gradient masks and center frosted selection lens.
  - Authentic momentum deceleration using `cubic-bezier(0.12, 0.9, 0.22, 1.05)`.
  - Mechanical haptic tick audio synthesized via the Web Audio API.
- **Vercel & Emil Kowalski Design Craft**:
  - OLED deep dark theme (`#000000`) with subtle ambient glow.
  - `font-variant-numeric: tabular-nums` to eliminate jitter.
  - Keyboard shortcuts (`R` / `Space` to spin, `C` to copy all).
  - Sonner-style stacked toast alerts.
  - Full `@media (prefers-reduced-motion: reduce)` accessibility compliance.

---

## Channel Schedule Windows

| Channel / Language | Format | Time Window (IST) | Strategy |
| :--- | :--- | :--- | :--- |
| **Hindi & Gujarati** | Long-Form | `4:00 PM – 5:15 PM` (Weekdays)<br>`9:00 AM – 10:15 AM` (Weekends) | Upload 1–2 hours before the 6–9 PM Indian watch peak |
| **Hindi & Gujarati** | Shorts | `5:30 PM – 7:00 PM` (Weekdays)<br>`12:30 PM – 2:30 PM` (Weekends) | Commute return & lunch-break mobile scroll |
| **English (US Focus)** | Long-Form | `12:30 AM – 1:30 AM` **(+1 Day)** | Hits US East Coast afternoon (2–3 PM EST) |
| **English (US Focus)** | Shorts | `1:45 AM – 2:45 AM` **(+1 Day)** | Pairs immediately after the US Long-form release |

---

## Keyboard Shortcuts

- <kbd>R</kbd> or <kbd>Space</kbd> — Spin all slot drums
- <kbd>C</kbd> — Copy complete schedule plan to clipboard

---

## Tech Stack

- Semantic HTML5 & CSS3 with CSS Variables
- Vanilla JavaScript (Zero runtime dependencies, ultra-lightweight)
- Web Audio API for synthetic mechanical ticks
- Deployed on **Vercel**
