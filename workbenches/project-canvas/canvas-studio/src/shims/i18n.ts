export const useTranslation = () => ({
  t: (key: string, defaultValue?: string) => defaultValue ?? key,
});
