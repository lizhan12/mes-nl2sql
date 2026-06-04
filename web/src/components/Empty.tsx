import { cn } from "@/lib/utils";

export default function Empty() {
  return (
    <div className={cn("flex h-full items-center justify-center")}>
      <p className="text-sm text-text-tertiary">暂无数据</p>
    </div>
  );
}
