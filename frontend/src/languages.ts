/**
 * The app's one real supported-language list — shared by `TopBar.tsx`
 * (the ops language selector) and `AlertComposer.tsx` (the human-preview
 * language tabs, "matching the top bar's language list" per User Flow
 * §3.4) so the two never independently drift. Real codes, per
 * `backend/stage4/config.py`'s own `supported_languages` default.
 */
export interface Language {
  code: string
  label: string
}

export const LANGUAGES: Language[] = [
  { code: 'en', label: 'English' },
  { code: 'ta', label: 'Tamil' },
  { code: 'hi', label: 'Hindi' },
  { code: 'te', label: 'Telugu' },
  { code: 'ml', label: 'Malayalam' },
  { code: 'kn', label: 'Kannada' },
]

export function languageLabel(code: string): string {
  return LANGUAGES.find((lang) => lang.code === code)?.label ?? code
}
