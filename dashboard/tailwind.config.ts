import type { Config } from 'tailwindcss';

export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        ink: '#07100f',
        panel: '#0c1715',
        line: '#22322e',
        mint: '#70f0b6',
        cyan: '#52d3ff',
        amber: '#ffbd66',
        coral: '#ff806d',
      },
      fontFamily: {
        sans: ['Inter', 'ui-sans-serif', 'system-ui'],
        mono: ['"JetBrains Mono"', 'ui-monospace', 'monospace'],
      },
      boxShadow: { glow: '0 0 40px rgba(112, 240, 182, 0.08)' },
    },
  },
  plugins: [],
} satisfies Config;
