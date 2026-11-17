# JAADOO landing page

A single-page, fully animated landing site for JAADOO, an AI virtual agent who is an alien visiting Earth.
It is plain HTML, CSS and JavaScript. There is no build step, backend or database.

## Project structure

```
Jaadoo/
├── index.html            Page markup (Hero, About, Final section)
├── css/styles.css        All styles, colour tokens and animations
├── js/main.js            Stars, parallax and alien wave
├── assets/images/
│   ├── jaadoo-alien.jpg  Alien character
│   └── space-nebula.jpg  Background nebula
├── package.json          Optional: provides `npm start`
└── README.md
```

## Run it

**Option 1: no install.** Unzip the folder and double-click `index.html`.

**Option 2: local server (recommended).** Requires Node.js 16+.

```
cd Jaadoo
npm start
```

Then open http://localhost:3000. Python also works: `python3 -m http.server 3000`.

## Notes

- Fonts (Space Grotesk, DM Sans) load from Google Fonts, so an internet connection is needed to see them. Offline, the page falls back to system fonts.
- Colours are defined as CSS variables at the top of `css/styles.css` (`--void`, `--navy`, `--violet`, `--pink`, `--lime`, `--ice`, `--mute`).
- To deploy, upload the folder to any static host (Netlify, GitHub Pages, Vercel).
