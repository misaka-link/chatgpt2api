"use client";

import { useEffect, useState } from "react";
import { LoaderCircle, Pencil, Plus, RefreshCw, Save, ShieldCheck, Trash2 } from "lucide-react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Textarea } from "@/components/ui/textarea";
import {
  deleteRegisterReputationBlacklistedDomain,
  deleteRegisterReputationDomain,
  fetchRegisterReputation,
  type RegisterReputation,
  type RegisterReputationBlacklistedDomain,
  type RegisterReputationDomain,
  upsertRegisterReputationBlacklistedDomain,
  upsertRegisterReputationDomain,
} from "@/lib/api";

type BlacklistDialogState = {
  open: boolean;
  previousDomain: string;
  value: string;
  reason: string;
};

type DomainDialogState = {
  open: boolean;
  previousDomain: string;
  domain: string;
};

const EMPTY_BLACKLIST_DIALOG: BlacklistDialogState = {
  open: false,
  previousDomain: "",
  value: "",
  reason: "",
};

const EMPTY_DOMAIN_DIALOG: DomainDialogState = {
  open: false,
  previousDomain: "",
  domain: "",
};

function formatTime(value: string) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "-";
  return new Intl.DateTimeFormat(undefined, {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).format(date);
}

function BlacklistDialog({
  open,
  state,
  pending,
  onOpenChange,
  onChange,
  onSubmit,
}: {
  open: boolean;
  state: BlacklistDialogState;
  pending: boolean;
  onOpenChange: (open: boolean) => void;
  onChange: (state: BlacklistDialogState) => void;
  onSubmit: () => void;
}) {
  const title = state.previousDomain ? "编辑黑名单域名" : "新增黑名单域名";
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="rounded-2xl">
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
        </DialogHeader>
        <div className="space-y-3">
          <div className="space-y-2">
            <label className="text-sm text-stone-700">域名或邮箱</label>
            <Input
              value={state.value}
              onChange={(event) => onChange({ ...state, value: event.target.value })}
              placeholder="user@example.com 或 example.com"
              className="h-10 rounded-xl border-stone-200 bg-white"
              disabled={pending}
            />
            <p className="text-xs leading-5 text-stone-500">保存时会自动提取 `@` 后面的域名部分。</p>
          </div>
          <div className="space-y-2">
            <label className="text-sm text-stone-700">原因</label>
            <Textarea
              value={state.reason}
              onChange={(event) => onChange({ ...state, reason: event.target.value })}
              placeholder="registration_disallowed"
              className="min-h-24 rounded-xl border-stone-200 bg-white text-sm"
              disabled={pending}
            />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" className="rounded-xl" onClick={() => onOpenChange(false)} disabled={pending}>
            取消
          </Button>
          <Button className="rounded-xl bg-stone-950 text-white hover:bg-stone-800" onClick={onSubmit} disabled={pending}>
            {pending ? <LoaderCircle className="size-4 animate-spin" /> : <Save className="size-4" />}
            保存
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function DomainDialog({
  open,
  state,
  pending,
  onOpenChange,
  onChange,
  onSubmit,
}: {
  open: boolean;
  state: DomainDialogState;
  pending: boolean;
  onOpenChange: (open: boolean) => void;
  onChange: (state: DomainDialogState) => void;
  onSubmit: () => void;
}) {
  const title = state.previousDomain ? "编辑信任域名" : "新增信任域名";
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="rounded-2xl">
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
        </DialogHeader>
        <div className="space-y-2">
          <label className="text-sm text-stone-700">域名</label>
          <Input
            value={state.domain}
            onChange={(event) => onChange({ ...state, domain: event.target.value })}
            placeholder="example.com"
            className="h-10 rounded-xl border-stone-200 bg-white"
            disabled={pending}
          />
          <p className="text-xs leading-5 text-stone-500">保存后会把这个域名重置为可优先复用的健康状态。</p>
        </div>
        <DialogFooter>
          <Button variant="outline" className="rounded-xl" onClick={() => onOpenChange(false)} disabled={pending}>
            取消
          </Button>
          <Button className="rounded-xl bg-stone-950 text-white hover:bg-stone-800" onClick={onSubmit} disabled={pending}>
            {pending ? <LoaderCircle className="size-4 animate-spin" /> : <Save className="size-4" />}
            保存
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function BlacklistRows({
  items,
  pendingKey,
  onEdit,
  onDelete,
}: {
  items: RegisterReputationBlacklistedDomain[];
  pendingKey: string;
  onEdit: (item: RegisterReputationBlacklistedDomain) => void;
  onDelete: (item: RegisterReputationBlacklistedDomain) => void;
}) {
  if (!items.length) {
    return <div className="rounded-xl border border-dashed border-stone-200 bg-white px-4 py-6 text-sm text-stone-500">当前没有黑名单域名。</div>;
  }
  return (
    <div className="overflow-hidden rounded-xl border border-stone-200 bg-white">
      <Table>
        <TableHeader>
          <TableRow className="hover:bg-transparent">
            <TableHead>域名</TableHead>
            <TableHead>原因</TableHead>
            <TableHead>更新时间</TableHead>
            <TableHead className="w-[120px]">操作</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {items.map((item) => {
            const disabled = pendingKey === item.domain;
            return (
              <TableRow key={item.domain}>
                <TableCell className="font-mono text-xs text-stone-700">{item.domain}</TableCell>
                <TableCell className="max-w-[240px] break-words text-xs text-stone-600">{item.reason || "-"}</TableCell>
                <TableCell className="text-xs text-stone-500">{formatTime(item.updated_at)}</TableCell>
                <TableCell>
                  <div className="flex items-center gap-2">
                    <Button type="button" variant="outline" className="h-8 rounded-lg px-2 text-xs" onClick={() => onEdit(item)} disabled={disabled}>
                      <Pencil className="size-3.5" />
                      编辑
                    </Button>
                    <Button type="button" variant="outline" className="h-8 rounded-lg border-rose-200 px-2 text-xs text-rose-600 hover:bg-rose-50" onClick={() => onDelete(item)} disabled={disabled}>
                      <Trash2 className="size-3.5" />
                      删除
                    </Button>
                  </div>
                </TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
    </div>
  );
}

function DomainRows({
  items,
  pendingKey,
  onEdit,
  onDelete,
}: {
  items: RegisterReputationDomain[];
  pendingKey: string;
  onEdit: (item: RegisterReputationDomain) => void;
  onDelete: (item: RegisterReputationDomain) => void;
}) {
  if (!items.length) {
    return <div className="rounded-xl border border-dashed border-stone-200 bg-white px-4 py-6 text-sm text-stone-500">当前没有信任域名。</div>;
  }
  return (
    <div className="overflow-hidden rounded-xl border border-stone-200 bg-white">
      <Table>
        <TableHeader>
          <TableRow className="hover:bg-transparent">
            <TableHead>域名</TableHead>
            <TableHead>状态</TableHead>
            <TableHead>统计</TableHead>
            <TableHead>最近成功</TableHead>
            <TableHead className="w-[120px]">操作</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {items.map((item) => {
            const disabled = pendingKey === item.domain;
            return (
              <TableRow key={item.domain}>
                <TableCell className="font-mono text-xs text-stone-700">{item.domain}</TableCell>
                <TableCell>
                  <Badge variant={item.healthy ? "success" : "secondary"} className="rounded-md">
                    {item.healthy ? "健康" : "降级"}
                  </Badge>
                </TableCell>
                <TableCell className="text-xs text-stone-600">
                  成功 {item.success} / 硬失败 {item.hard_fail} / 软失败 {item.soft_fail}
                </TableCell>
                <TableCell className="text-xs text-stone-500">{formatTime(item.last_success_at)}</TableCell>
                <TableCell>
                  <div className="flex items-center gap-2">
                    <Button type="button" variant="outline" className="h-8 rounded-lg px-2 text-xs" onClick={() => onEdit(item)} disabled={disabled}>
                      <Pencil className="size-3.5" />
                      编辑
                    </Button>
                    <Button type="button" variant="outline" className="h-8 rounded-lg border-rose-200 px-2 text-xs text-rose-600 hover:bg-rose-50" onClick={() => onDelete(item)} disabled={disabled}>
                      <Trash2 className="size-3.5" />
                      删除
                    </Button>
                  </div>
                </TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
    </div>
  );
}

export function YydsLearningPanel({
  provider,
  providerRef,
}: {
  provider: string;
  providerRef: string;
}) {
  const [reputation, setReputation] = useState<RegisterReputation | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [pendingKey, setPendingKey] = useState("");
  const [blacklistDialog, setBlacklistDialog] = useState<BlacklistDialogState>(EMPTY_BLACKLIST_DIALOG);
  const [domainDialog, setDomainDialog] = useState<DomainDialogState>(EMPTY_DOMAIN_DIALOG);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      setIsLoading(true);
      try {
        const data = await fetchRegisterReputation(provider, providerRef);
        if (!cancelled) {
          setReputation(data.reputation);
        }
      } catch (error) {
        if (!cancelled) {
          toast.error(error instanceof Error ? error.message : "加载学习模式列表失败");
        }
      } finally {
        if (!cancelled) {
          setIsLoading(false);
        }
      }
    };
    void load();
    return () => {
      cancelled = true;
    };
  }, [provider, providerRef]);

  const handleReload = async () => {
    setIsLoading(true);
    try {
      const data = await fetchRegisterReputation(provider, providerRef);
      setReputation(data.reputation);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "刷新学习模式列表失败");
    } finally {
      setIsLoading(false);
    }
  };

  const saveBlacklistedDomain = async () => {
    const value = blacklistDialog.value.trim();
    if (!value) {
      toast.error("域名或邮箱不能为空");
      return;
    }
    const pendingValue = blacklistDialog.previousDomain || value;
    setPendingKey(pendingValue);
    try {
      const data = await upsertRegisterReputationBlacklistedDomain({
        provider,
        provider_ref: providerRef,
        domain: value,
        reason: blacklistDialog.reason.trim(),
        previous_domain: blacklistDialog.previousDomain,
      });
      setReputation(data.reputation);
      setBlacklistDialog(EMPTY_BLACKLIST_DIALOG);
      toast.success("黑名单域名已保存");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "保存黑名单域名失败");
    } finally {
      setPendingKey("");
    }
  };

  const deleteBlacklistedDomain = async (item: RegisterReputationBlacklistedDomain) => {
    if (!window.confirm(`确定删除黑名单域名 ${item.domain} 吗？`)) {
      return;
    }
    setPendingKey(item.domain);
    try {
      const data = await deleteRegisterReputationBlacklistedDomain({
        provider,
        provider_ref: providerRef,
        domain: item.domain,
      });
      setReputation(data.reputation);
      toast.success("黑名单域名已删除");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "删除黑名单域名失败");
    } finally {
      setPendingKey("");
    }
  };

  const saveDomain = async () => {
    const domain = domainDialog.domain.trim();
    if (!domain) {
      toast.error("域名不能为空");
      return;
    }
    setPendingKey(domainDialog.previousDomain || domain);
    try {
      const data = await upsertRegisterReputationDomain({
        provider,
        provider_ref: providerRef,
        domain,
        previous_domain: domainDialog.previousDomain,
      });
      setReputation(data.reputation);
      setDomainDialog(EMPTY_DOMAIN_DIALOG);
      toast.success("信任域名已保存");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "保存信任域名失败");
    } finally {
      setPendingKey("");
    }
  };

  const deleteDomain = async (item: RegisterReputationDomain) => {
    if (!window.confirm(`确定删除信任域名 ${item.domain} 吗？`)) {
      return;
    }
    setPendingKey(item.domain);
    try {
      const data = await deleteRegisterReputationDomain({
        provider,
        provider_ref: providerRef,
        domain: item.domain,
      });
      setReputation(data.reputation);
      toast.success("信任域名已删除");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "删除信任域名失败");
    } finally {
      setPendingKey("");
    }
  };

  const blacklistedItems = reputation?.blacklisted_domains || [];
  const domainItems = reputation?.trusted_domains || [];
  const dialogPending = pendingKey !== "";

  return (
    <div className="space-y-4 rounded-2xl border border-stone-200 bg-stone-50/70 p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="space-y-1">
          <div className="flex items-center gap-2 text-sm font-semibold text-stone-800">
            <ShieldCheck className="size-4 text-emerald-600" />
            YYDSMail 学习模式列表
          </div>
          <p className="text-xs leading-5 text-stone-500">
            黑名单和信任列表都按域名统计。输入完整邮箱时会自动提取域名部分，修改后立即生效，不需要再点上面的“保存配置”。
          </p>
        </div>
        <Button type="button" variant="outline" className="h-8 rounded-lg px-3 text-xs" onClick={() => void handleReload()} disabled={isLoading}>
          {isLoading ? <LoaderCircle className="size-3.5 animate-spin" /> : <RefreshCw className="size-3.5" />}
          刷新
        </Button>
      </div>

      {isLoading && !reputation ? (
        <div className="flex items-center justify-center rounded-xl border border-stone-200 bg-white px-4 py-10">
          <LoaderCircle className="size-5 animate-spin text-stone-400" />
        </div>
      ) : (
        <div className="grid gap-4 xl:grid-cols-2">
          <div className="space-y-3">
            <div className="flex items-center justify-between gap-3">
              <div className="flex items-center gap-2">
                <h4 className="text-sm font-semibold text-stone-800">黑名单域名</h4>
                <Badge variant="secondary" className="rounded-md">{blacklistedItems.length}</Badge>
              </div>
              <Button type="button" variant="outline" className="h-8 rounded-lg px-3 text-xs" onClick={() => setBlacklistDialog({ ...EMPTY_BLACKLIST_DIALOG, open: true })} disabled={dialogPending}>
                <Plus className="size-3.5" />
                新增
              </Button>
            </div>
            <BlacklistRows
              items={blacklistedItems}
              pendingKey={pendingKey}
              onEdit={(item) =>
                setBlacklistDialog({
                  open: true,
                  previousDomain: item.domain,
                  value: item.domain,
                  reason: item.reason,
                })
              }
              onDelete={(item) => void deleteBlacklistedDomain(item)}
            />
          </div>

          <div className="space-y-3">
            <div className="flex items-center justify-between gap-3">
              <div className="flex items-center gap-2">
                <h4 className="text-sm font-semibold text-stone-800">信任域名列表</h4>
                <Badge variant="secondary" className="rounded-md">{domainItems.length}</Badge>
              </div>
              <Button type="button" variant="outline" className="h-8 rounded-lg px-3 text-xs" onClick={() => setDomainDialog({ ...EMPTY_DOMAIN_DIALOG, open: true })} disabled={dialogPending}>
                <Plus className="size-3.5" />
                新增
              </Button>
            </div>
            <DomainRows
              items={domainItems}
              pendingKey={pendingKey}
              onEdit={(item) => setDomainDialog({ open: true, previousDomain: item.domain, domain: item.domain })}
              onDelete={(item) => void deleteDomain(item)}
            />
          </div>
        </div>
      )}

      <BlacklistDialog
        open={blacklistDialog.open}
        state={blacklistDialog}
        pending={dialogPending}
        onOpenChange={(open) => {
          if (!open && !dialogPending) setBlacklistDialog(EMPTY_BLACKLIST_DIALOG);
        }}
        onChange={setBlacklistDialog}
        onSubmit={() => void saveBlacklistedDomain()}
      />
      <DomainDialog
        open={domainDialog.open}
        state={domainDialog}
        pending={dialogPending}
        onOpenChange={(open) => {
          if (!open && !dialogPending) setDomainDialog(EMPTY_DOMAIN_DIALOG);
        }}
        onChange={setDomainDialog}
        onSubmit={() => void saveDomain()}
      />
    </div>
  );
}
