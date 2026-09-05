"use client";

import { useCallback, useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useToast } from "@/components/hooks/use-toast";
import { parseApiError } from "@/lib/utils";
import { providerService } from "@/services/providerService";
import type { OrgSpend } from "@/types/models";

function formatUsd(value: number | null): string {
  if (value === null) return "No cap";
  return `$${value.toFixed(2)}`;
}

interface BudgetCardProps {
  admin: boolean;
}

// GET/PUT /v1alpha1/organizations/current/{spend,budget}: the LiteLLM team
// budget for the caller's organization (backend/api/organizations.py). Every
// member reads it; only an admin can change budget_usd.
export function BudgetCard({ admin }: BudgetCardProps) {
  const { toast } = useToast();
  const [spend, setSpend] = useState<OrgSpend | null>(null);
  const [budgetInput, setBudgetInput] = useState("");
  const [saving, setSaving] = useState(false);

  const fetchSpend = useCallback(async () => {
    try {
      const data = await providerService.getSpend();
      setSpend(data);
      setBudgetInput(data.budget_usd !== null ? String(data.budget_usd) : "");
    } catch (error) {
      toast(parseApiError(error));
    }
  }, [toast]);

  useEffect(() => {
    fetchSpend();
  }, [fetchSpend]);

  const handleSave = async () => {
    const trimmed = budgetInput.trim();
    const value = trimmed === "" ? null : Number(trimmed);
    if (value !== null && (Number.isNaN(value) || value < 0)) {
      toast({
        title: "Invalid budget",
        description: "Enter a non-negative number, or clear it for no cap.",
        variant: "destructive",
      });
      return;
    }
    setSaving(true);
    try {
      const data = await providerService.updateBudget(value);
      setSpend(data);
      toast({
        title: "Success",
        description: "Budget saved",
        variant: "success",
      });
    } catch (error) {
      toast(parseApiError(error));
    } finally {
      setSaving(false);
    }
  };

  if (!spend) return null;

  return (
    <Card>
      <CardHeader>
        <CardTitle>Monthly spend</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex flex-wrap gap-6 text-sm">
          <div>
            <p className="text-muted-foreground">Spend</p>
            <p className="text-lg font-semibold">${spend.spend.toFixed(2)}</p>
          </div>
          <div>
            <p className="text-muted-foreground">Cap</p>
            <p className="text-lg font-semibold">
              {formatUsd(spend.max_budget)}
            </p>
          </div>
          {spend.budget_reset_at && (
            <div>
              <p className="text-muted-foreground">Resets</p>
              <p className="text-lg font-semibold">
                {new Date(spend.budget_reset_at).toLocaleDateString()}
              </p>
            </div>
          )}
        </div>
        {admin && (
          <div className="flex items-end gap-2">
            <div className="space-y-2">
              <Label htmlFor="org-budget">Monthly budget (USD)</Label>
              {/* type="text" (not "number") so the field keeps the
                  "textbox" accessible role the fast tier targets. */}
              <Input
                id="org-budget"
                type="text"
                inputMode="decimal"
                value={budgetInput}
                onChange={(e) => setBudgetInput(e.target.value)}
                placeholder="No cap"
                className="w-40"
              />
            </div>
            <Button onClick={handleSave} loading={saving}>
              Save budget
            </Button>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
