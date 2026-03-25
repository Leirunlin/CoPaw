export { SkillCard } from "./SkillCard";
export { SkillDrawer, parseFrontmatter } from "./SkillDrawer";
export {
  getFileIcon,
  getSkillDisplaySource,
  getSkillVisual,
} from "./SkillCard";

export const SUPPORTED_SKILL_URL_PREFIXES = [
  "https://skills.sh/",
  "https://clawhub.ai/",
  "https://skillsmp.com/",
  "https://lobehub.com/",
  "https://market.lobehub.com/",
  "https://github.com/",
  "https://modelscope.cn/skills/",
];

export function isSupportedSkillUrl(url: string): boolean {
  return SUPPORTED_SKILL_URL_PREFIXES.some((prefix) => url.startsWith(prefix));
}
