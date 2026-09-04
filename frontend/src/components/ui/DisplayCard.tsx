import React from "react";
import Image from "next/image";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { RefreshButton } from "@/components/RefreshButton";

interface DisplayCardProps {
  icon?: string | React.ReactNode;
  title: React.ReactNode;
  description?: React.ReactNode;
  content?: React.ReactNode;
  footer?: React.ReactNode;
  className?: string;
  onClick?: () => void;
  onRefresh?: () => Promise<void>;
}

export function DisplayCard({
  icon,
  title,
  description,
  content,
  footer,
  className,
  onClick,
  onRefresh,
}: DisplayCardProps) {
  return (
    <Card className={`flex flex-col h-full ${className}`} onClick={onClick}>
      <CardHeader className="grow">
        <div className="flex justify-between">
          <div className="flex items-start space-x-4">
            {icon &&
              (typeof icon === "string" ? (
                <div className="relative w-9 h-9">
                  <Image
                    src={icon}
                    alt="Icon"
                    layout="fill"
                    objectFit="contain"
                    className="rounded-md"
                  />
                </div>
              ) : (
                icon
              ))}
            <div>
              <CardTitle>{title}</CardTitle>
              {description && <CardDescription>{description}</CardDescription>}
            </div>
          </div>
          {onRefresh && <RefreshButton onRefresh={onRefresh} />}
        </div>
      </CardHeader>
      {content && <CardContent>{content}</CardContent>}
      {footer && <CardFooter className="mt-auto">{footer}</CardFooter>}
    </Card>
  );
}
