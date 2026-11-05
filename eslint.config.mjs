import js from '@eslint/js';
import globals from 'globals';

export default [
  { ignores: ['frontend/web/vendor/**', 'node_modules/**', 'work/**'] },
  js.configs.recommended,
  {
    files: ['frontend/web/*.js'],
    languageOptions: { sourceType: 'script', globals: globals.browser },
    rules: {
      'no-unused-vars': ['error', { argsIgnorePattern: '^_', caughtErrors: 'none' }],
    },
  },
  {
    files: ['frontend/web/parking-3d.js', 'frontend/web/uth-route.js'],
    languageOptions: { sourceType: 'module' },
  },
  {
    files: ['tests/*.cjs'],
    languageOptions: { sourceType: 'commonjs', globals: globals.node },
    rules: {
      'no-unused-vars': ['error', { argsIgnorePattern: '^_', caughtErrors: 'none' }],
    },
  },
];
