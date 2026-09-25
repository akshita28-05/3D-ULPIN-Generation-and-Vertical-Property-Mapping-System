export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      colors: {
        ink: {
          950: '#0B1917',
          900: '#12251F',
          800: '#1A332B',
          700: '#254238',
        },
        brand: {
          400: '#C9A24E',
          500: '#A9822F',
          600: '#876A24',
        },
        gold: {
          400: '#3E7268',
          500: '#2C5B53',
        },
        cream: '#F3EEE1',
        'cream-2': '#EAE2CC',
        panel: '#FBF9F2',
        brick: '#9C402A',
        moss: '#4B7355',
      },
      fontFamily: {
        sans: ['"IBM Plex Sans"', 'system-ui', 'sans-serif'],
        display: ['"Spectral"', 'Georgia', 'serif'],
        mono: ['"IBM Plex Mono"', 'ui-monospace', 'monospace'],
      },
      boxShadow: {
        glow: '0 12px 32px rgba(15, 35, 30, 0.18)',
      },
      backgroundImage: {
        'grid-pattern': 'none',
      },
    },
  },
  plugins: [],
}
