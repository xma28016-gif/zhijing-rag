"use client";

import { useQuery } from "@tanstack/react-query";
import { cn } from "@/lib/utils";

type Health = { status: string; checks?: Record<string, string> };
const names: Record<string, string> = {
  application: "接口服务", postgres: "数据存储", redis: "任务队列", storage: "文件存储", worker: "后台处理",
};

export function ServiceHealth() {
  const health = useQuery({
    queryKey: ["service-readiness"], refetchInterval: 15_000, retry: false,
    queryFn: async (): Promise<Health> => {
      const response = await fetch("/api/v1/health/ready", { cache: "no-store" });
      const result = await response.json() as Health;
      if (!result.status) throw new Error("服务不可达");
      return result;
    },
  });
  const ready = health.data?.status === "ready";
  return <details className="relative hidden md:block">
    <summary className={cn("cursor-pointer list-none rounded-full border px-3 py-1.5 text-xs font-medium",
      ready ? "border-emerald-200 bg-emerald-50 text-emerald-700" : "border-amber-200 bg-amber-50 text-amber-800")}>
      {health.isLoading ? "正在检查服务…" : ready ? "服务运行正常" : "部分服务未就绪"}
    </summary>
    <div className="absolute right-0 top-10 z-50 w-64 space-y-2 rounded-xl border bg-white p-4 text-xs shadow-xl">
      {health.isError ? <p>无法连接后端，请运行项目启动脚本。</p> : Object.entries(health.data?.checks ?? {}).map(([key, value]) =>
        <p key={key} className="flex justify-between"><span>{names[key] ?? key}</span><span className={value === "ok" ? "text-emerald-700" : "text-red-700"}>{value === "ok" ? "正常" : "不可用"}</span></p>)}
      <button className="pt-2 text-indigo-700" onClick={() => { void health.refetch(); }}>重新检查</button>
    </div>
  </details>;
}
