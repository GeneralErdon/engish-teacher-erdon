/**
 * Conventional Commits, checked on every commit (`commit-msg` hook) and on every pull request
 * (CI `Commit messages` job). Same rules as the other GeneralErdon projects.
 *
 * @type {import('@commitlint/types').UserConfig}
 */
export default {
  extends: ['@commitlint/config-conventional'],
  rules: {
    'type-enum': [
      2,
      'always',
      [
        'feat',
        'fix',
        'perf',
        'refactor',
        'docs',
        'test',
        'build',
        'ci',
        'chore',
        'style',
        'revert',
      ],
    ],
    // Optional scope; when present, one of the areas of the monorepo.
    'scope-enum': [
      2,
      'always',
      ['api', 'pron', 'contracts', 'desktop', 'ui', 'docker', 'ci', 'deps', 'docs', 'release'],
    ],
    'scope-case': [2, 'always', 'kebab-case'],
    'subject-case': [2, 'never', ['upper-case', 'pascal-case', 'start-case']],
    'subject-empty': [2, 'never'],
    'subject-full-stop': [2, 'never', '.'],
    'header-max-length': [2, 'always', 100],
    'body-max-line-length': [1, 'always', 120],
  },
}
