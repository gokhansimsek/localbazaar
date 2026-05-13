// Next.js 16 ships native flat-config presets — import them directly.
// No FlatCompat wrapper is needed (it triggers a circular-JSON validator bug).
import coreWebVitals from "eslint-config-next/core-web-vitals";
import typescript from "eslint-config-next/typescript";

const config = [
  {
    ignores: [".next/**", "node_modules/**", "dist/**", "build/**", "coverage/**", "next-env.d.ts"],
  },
  ...coreWebVitals,
  ...typescript,
  {
    rules: {
      // React 19 flags every fetch-then-setState in useEffect. That pattern is
      // intentional for client-side data fetching here; the proper migration is
      // React Query / SWR, which is out of scope for this scaffold.
      "react-hooks/set-state-in-effect": "off",
    },
  },
];

export default config;
