// ESLint v9+ flat config — TypeScript + Prettier interop.
// (external tool-generated folders) are excluded.

import tseslint from "@typescript-eslint/eslint-plugin";
import tsparser from "@typescript-eslint/parser";
import prettier from "eslint-config-prettier";

export default [
  {
    ignores: [
      "dist/**",
      "node_modules/**",
    ],
  },
  {
    files: ["src/**/*.ts", "test/**/*.ts"],
    languageOptions: {
      parser: tsparser,
      parserOptions: {
        ecmaVersion: 2022,
        sourceType: "module",
      },
      globals: {
        console: "readonly",
        process: "readonly",
        Buffer: "readonly",
        setTimeout: "readonly",
        clearTimeout: "readonly",
        setInterval: "readonly",
        clearInterval: "readonly",
        URL: "readonly",
        URLSearchParams: "readonly",
        fetch: "readonly",
        AbortController: "readonly",
        AbortSignal: "readonly",
        global: "readonly",
        globalThis: "readonly",
        __dirname: "readonly",
        __filename: "readonly",
      },
    },
    plugins: {
      "@typescript-eslint": tseslint,
    },
    rules: {
      // ---- Base recommended (manual subset for flat config) ----
      "no-undef": "off", // TS handles this
      "no-unused-vars": "off", // delegated to TS rule below
      "no-empty": ["error", { allowEmptyCatch: true }],
      "no-prototype-builtins": "warn",
      "no-useless-escape": "warn",
      "no-control-regex": "off",
      "no-constant-condition": ["error", { checkLoops: false }],
      "no-irregular-whitespace": "error",

      // ---- TypeScript rules ----
      "@typescript-eslint/no-unused-vars": [
        "error",
        {
          argsIgnorePattern: "^_",
          varsIgnorePattern: "^_",
          caughtErrorsIgnorePattern: "^_",
          destructuredArrayIgnorePattern: "^_",
        },
      ],
      "@typescript-eslint/no-explicit-any": "warn",
      "@typescript-eslint/no-non-null-assertion": "off",

      // ---- Style / safety ----
      "no-console": ["warn", { allow: ["error", "warn"] }],
      "prefer-const": "error",
      eqeqeq: ["error", "always", { null: "ignore" }],
    },
  },
  // Tests: console.* and any are a bit looser.
  {
    files: ["test/**/*.ts"],
    rules: {
      "no-console": "off",
      "@typescript-eslint/no-explicit-any": "off",
    },
  },
  // Prettier last — turns off formatting-conflicting rules.
  prettier,
];
