"use client";

import { useRouter } from "next/navigation";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import * as z from "zod";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { RocketIcon } from "@radix-ui/react-icons";
import {
  Form,
  FormControl,
  FormDescription,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form";
import { useToast } from "@/components/hooks/use-toast";
import { useState } from "react";
import { notebookService } from "@/services/notebookService";
import { parseApiError } from "@/lib/utils";

const NAME_MAX_LENGTH = 32;
// DNS-1123 label: lowercase alphanumeric, hyphens allowed in the middle,
// must start and end with an alphanumeric character.
const DNS_1123_LABEL_PATTERN = /^[a-z0-9]([-a-z0-9]*[a-z0-9])?$/;

// A cleared number input must not become NaN (React rejects NaN as a value);
// keep "" so the schema reports the range error instead.
const numberOrEmpty = (value: string) => (value === "" ? "" : Number(value));

const notebookSchema = z
  .object({
    name: z
      .string()
      .min(1, "Name is required")
      .max(
        NAME_MAX_LENGTH,
        `Name must be ${NAME_MAX_LENGTH} characters or fewer`
      )
      .regex(
        DNS_1123_LABEL_PATTERN,
        "Use lowercase letters, digits, and hyphens; must start and end with a letter or digit"
      ),
    type: z.enum(["jupyter", "vscode"]),
    framework: z.enum(["pytorch", "tensorflow"]).optional(),
    resources_cpu: z.coerce.number().min(0.5).max(4),
    resources_memory: z.coerce.number().min(1).max(32),
    nvidia_gpu: z.boolean(),
    // The GPU count input is unmounted while the GPU switch is off and can
    // leave an empty string behind; treat that as "not set".
    resources_gpu: z.preprocess(
      (value) => (value === "" || value === null ? undefined : value),
      z.coerce.number().min(1).max(4).optional()
    ),
    storage_size: z.coerce.number().min(5).max(20),
  })
  .refine(
    (data) => {
      if (data.type !== "jupyter") {
        return (
          data.framework === undefined &&
          data.nvidia_gpu === false &&
          data.resources_gpu === undefined
        );
      }
      return true;
    },
    {
      message: "Invalid configuration for this notebook type",
    }
  );

type NotebookFormValues = z.infer<typeof notebookSchema>;

export default function NewNotebookForm() {
  const router = useRouter();
  const { toast } = useToast();

  const form = useForm<NotebookFormValues>({
    resolver: zodResolver(notebookSchema),
    mode: "onChange",
    defaultValues: {
      name: "",
      type: "jupyter",
      framework: "pytorch",
      resources_cpu: 0.5,
      resources_memory: 1,
      nvidia_gpu: false,
      resources_gpu: undefined,
      storage_size: 5,
    },
  });

  const { watch } = form;
  const notebookType = watch("type");
  const nvidiaGpu = watch("nvidia_gpu");

  const [isSubmitting, setIsSubmitting] = useState(false);

  const onSubmit = async (data: NotebookFormValues) => {
    if (isSubmitting) return;
    setIsSubmitting(true);
    try {
      const updatedFormData = {
        ...data,
        resources_cpu: `${data.resources_cpu}`,
        resources_memory: `${data.resources_memory}Gi`,
        resources_gpu: data.resources_gpu ? `${data.resources_gpu}` : undefined,
        storage_size: `${data.storage_size}Gi`,
      };
      await notebookService.createNotebook(updatedFormData);
      toast({
        title: "Notebook created",
        description: "Your notebook has been successfully created.",
        variant: "success",
      });
      router.push("/notebooks");
    } catch (error) {
      toast(parseApiError(error));
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <Form {...form}>
      <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-6">
        <FormField
          control={form.control}
          name="name"
          render={({ field }) => (
            <FormItem>
              <FormLabel>Name</FormLabel>
              <FormControl>
                <Input {...field} maxLength={NAME_MAX_LENGTH} />
              </FormControl>
              <FormDescription>
                Lowercase letters, digits, and hyphens only; must start and end
                with a letter or digit. Up to {NAME_MAX_LENGTH} characters.
              </FormDescription>
              <FormMessage />
            </FormItem>
          )}
        />

        <FormField
          control={form.control}
          name="type"
          render={({ field }) => (
            <FormItem>
              <FormLabel>Type</FormLabel>
              <Select
                onValueChange={(e) => {
                  if (e != "jupyter") {
                    form.setValue("framework", undefined);
                    form.setValue("nvidia_gpu", false);
                    form.setValue("resources_gpu", undefined);
                  }
                  field.onChange(e);
                }}
                defaultValue={field.value}
              >
                <FormControl>
                  <SelectTrigger>
                    <SelectValue placeholder="Select type" />
                  </SelectTrigger>
                </FormControl>
                <SelectContent>
                  <SelectItem value="jupyter">Jupyter</SelectItem>
                  <SelectItem value="vscode">VSCode</SelectItem>
                </SelectContent>
              </Select>
              <FormMessage />
            </FormItem>
          )}
        />

        {notebookType === "jupyter" && (
          <FormField
            control={form.control}
            name="framework"
            render={({ field }) => (
              <FormItem>
                <FormLabel>Framework</FormLabel>
                <Select
                  onValueChange={field.onChange}
                  defaultValue={field.value}
                >
                  <FormControl>
                    <SelectTrigger>
                      <SelectValue placeholder="Select framework" />
                    </SelectTrigger>
                  </FormControl>
                  <SelectContent>
                    <SelectItem value="pytorch">PyTorch</SelectItem>
                    <SelectItem value="tensorflow">TensorFlow</SelectItem>
                  </SelectContent>
                </Select>
                <FormMessage />
              </FormItem>
            )}
          />
        )}

        <FormField
          control={form.control}
          name="resources_cpu"
          render={({ field }) => (
            <FormItem>
              <FormLabel>Resources CPU</FormLabel>
              <FormControl>
                <Input
                  type="number"
                  min={0.5}
                  max={4}
                  step={0.5}
                  {...field}
                  onChange={(e) =>
                    field.onChange(numberOrEmpty(e.target.value))
                  }
                />
              </FormControl>
              <FormMessage />
            </FormItem>
          )}
        />

        <FormField
          control={form.control}
          name="resources_memory"
          render={({ field }) => (
            <FormItem>
              <FormLabel>Resources Memory (GB)</FormLabel>
              <FormControl>
                <Input
                  type="number"
                  min={1}
                  max={32}
                  {...field}
                  onChange={(e) =>
                    field.onChange(numberOrEmpty(e.target.value))
                  }
                />
              </FormControl>
              <FormMessage />
            </FormItem>
          )}
        />

        {notebookType === "jupyter" && (
          <FormField
            control={form.control}
            name="nvidia_gpu"
            render={({ field }) => (
              <FormItem className="flex flex-row items-center justify-between rounded-lg border p-4">
                <div className="space-y-0.5">
                  <FormLabel className="text-base">Nvidia GPU</FormLabel>
                  <FormDescription>
                    Enable Nvidia GPU for this notebook
                  </FormDescription>
                </div>
                <FormControl>
                  <Switch
                    checked={field.value}
                    onCheckedChange={(e) => {
                      form.setValue("resources_gpu", e ? 1 : undefined);
                      field.onChange(e);
                    }}
                  />
                </FormControl>
              </FormItem>
            )}
          />
        )}

        {nvidiaGpu && (
          <FormField
            control={form.control}
            name="resources_gpu"
            render={({ field }) => (
              <FormItem>
                <FormLabel>Resources GPU</FormLabel>
                <FormControl>
                  <Input
                    type="number"
                    min={1}
                    max={4}
                    {...field}
                    onChange={(e) =>
                      field.onChange(numberOrEmpty(e.target.value))
                    }
                  />
                </FormControl>
                <FormMessage />
              </FormItem>
            )}
          />
        )}

        <FormField
          control={form.control}
          name="storage_size"
          render={({ field }) => (
            <FormItem>
              <FormLabel>Storage Size (GB)</FormLabel>
              <FormControl>
                <Input
                  type="number"
                  min={5}
                  max={20}
                  {...field}
                  onChange={(e) =>
                    field.onChange(numberOrEmpty(e.target.value))
                  }
                />
              </FormControl>
              <FormDescription>Minimum 5 GB, maximum 20 GB.</FormDescription>
              <FormMessage />
            </FormItem>
          )}
        />

        <Button
          type="submit"
          icon={<RocketIcon className="w-4 h-4" />}
          // Gate on reported errors rather than isValid: with coerced number
          // fields react-hook-form does not reliably flip isValid to true.
          disabled={
            isSubmitting || Object.keys(form.formState.errors).length > 0
          }
          loading={isSubmitting}
        >
          {isSubmitting ? "Launching..." : "Launch"}
        </Button>
      </form>
    </Form>
  );
}
