"use client";

import Link from "next/link";
import { Button } from "@/components/ui/button";
import Dashboard from "@/components/Dashboard";
import {
  CodeIcon,
  CubeIcon,
  LayersIcon,
  Pencil2Icon,
} from "@radix-ui/react-icons";
import { DisplayCard } from "@/components/ui/DisplayCard";

const homecatalogs: {
  icon: React.ReactNode;
  title: string;
  description: string;
  content?: string;
  buttons: { link: string; text: string; variant: "default" | "secondary" }[];
}[] = [
  {
    icon: <CubeIcon className="mr-2 h-8 w-8" />,
    title: "Models",
    description: "Explore our AI models",
    content: "Pretrained models for your use cases",
    buttons: [
      {
        link: "/models/catalog",
        text: "View Catalog",
        variant: "default",
      },
      {
        link: "/models/endpoints",
        text: "View Instances",
        variant: "secondary",
      },
    ],
  },
  {
    icon: <LayersIcon className="mr-2 h-8 w-8" />,
    title: "Vector Databases",
    description: "Explore our vector databases",
    content: "Implement RAG apps with your own data",
    buttons: [
      {
        link: "/vector-databases/catalog",
        text: "View Catalog",
        variant: "default",
      },
      {
        link: "/vector-databases/endpoints",
        text: "View Instances",
        variant: "secondary",
      },
    ],
  },
  {
    icon: <Pencil2Icon className="mr-2 h-8 w-8" />,
    title: "Notebooks",
    description: "Explore our notebooks",
    content: "Interactive environment for data science and machine learning",
    buttons: [
      {
        link: "/notebooks/",
        text: "View Notebooks",
        variant: "default" as const,
      },
    ],
  },
  {
    icon: <CodeIcon className="mr-2 h-8 w-8" />,
    title: "Develop",
    description: "Quickly prototype AI applications",
    content: "Build AI apps with low-code graphical interface",
    buttons: [
      {
        link: "/develop/",
        text: "Develop AI App",
        variant: "default",
      },
    ],
  },
];

export default function Home() {
  return (
    <Dashboard title="Welcome to AI Hub">
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {homecatalogs.map((catalog, index) => (
          <DisplayCard
            key={index}
            icon={catalog.icon}
            title={catalog.title}
            description={catalog.description}
            content={catalog.content}
            footer={
              <div className="flex flex-row gap-2 mb-3 w-full">
                {catalog.buttons.map((button, index) => (
                  <Link key={index} href={button.link} passHref>
                    <Button variant={button.variant} className="w-full py-2">
                      {button.text}
                    </Button>
                  </Link>
                ))}
              </div>
            }
          />
        ))}
      </div>
    </Dashboard>
  );
}
