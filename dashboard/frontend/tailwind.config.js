/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        // Command center dark theme
        'cc-bg': '#0a0e17',
        'cc-surface': '#111827',
        'cc-card': '#1a2332',
        'cc-border': '#2a3548',
        'cc-text': '#e2e8f0',
        'cc-muted': '#64748b',
        'cc-accent': '#3b82f6',
        'cc-green': '#22c55e',
        'cc-red': '#ef4444',
        'cc-yellow': '#eab308',
        'cc-purple': '#a855f7',
      },
      fontFamily: {
        'mono': ['IBM Plex Mono', 'JetBrains Mono', 'monospace'],
        'display': ['Space Grotesk', 'system-ui', 'sans-serif'],
      },
    },
  },
  plugins: [],
}
