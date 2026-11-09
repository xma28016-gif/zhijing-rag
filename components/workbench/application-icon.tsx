import { BookOpen, FileCheck2, FileText, Headphones, Megaphone, NotebookPen } from "lucide-react";
import { applicationCategories, type BusinessApplication } from "@/lib/workbench-apps";

const icons = { report: FileText, support: Headphones, review: FileCheck2, marketing: Megaphone, meeting: NotebookPen, policy: BookOpen };

export function ApplicationIcon({ app, small = false }: { app: BusinessApplication; small?: boolean }) {
  const category = applicationCategories.find((item) => item.id === app.category)!;
  const Icon = icons[app.icon];
  return <span aria-hidden="true" className={`flex shrink-0 items-center justify-center rounded-xl ${small ? "h-9 w-9" : "h-12 w-12"} ${category.accent} text-white`}><Icon size={small ? 18 : 23} strokeWidth={1.8} /></span>;
}
