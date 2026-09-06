import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  NavigationMenu,
  NavigationMenuContent,
  NavigationMenuItem,
  NavigationMenuLink,
  NavigationMenuList,
  NavigationMenuTrigger,
  navigationMenuTriggerStyle,
} from "@/components/ui/navigation-menu";
import { useTheme } from "next-themes";
import { ThemeDropdown } from "./ThemeDropdown";
import { MobileNav } from "./MobileNav";
import { UserMenu } from "./UserMenu";
import { AUTH_DISABLED } from "@/constants";
import { cn } from "@/lib/utils";
import {
  BarChartIcon,
  ChatBubbleIcon,
  CodeIcon,
  CubeIcon,
  IdCardIcon,
  LayersIcon,
  Pencil2Icon,
} from "@radix-ui/react-icons";

const menuItems = [
  {
    label: "Notebooks",
    icon: <Pencil2Icon className="mr-2 h-4 w-4" />,
    href: "/notebooks",
  },
  {
    label: "Models",
    icon: <CubeIcon className="mr-2 h-4 w-4" />,
    items: [
      {
        label: "Catalog",
        href: "/models/catalog",
        description: "Browse and select from a variety of AI models",
      },
      {
        label: "Registry",
        href: "/models/registry",
        description: "Import, publish and manage the model catalog",
      },
      {
        label: "Instances",
        href: "/models/endpoints",
        description: "Manage and monitor your deployed model instances",
      },
    ],
  },
  {
    label: "Chat",
    icon: <ChatBubbleIcon className="mr-2 h-4 w-4" />,
    href: "/chat",
  },
  {
    label: "Providers",
    icon: <IdCardIcon className="mr-2 h-4 w-4" />,
    href: "/providers",
  },
  {
    label: "Usage",
    icon: <BarChartIcon className="mr-2 h-4 w-4" />,
    href: "/usage",
  },
  {
    label: "Vector Databases",
    icon: <LayersIcon className="mr-2 h-4 w-4" />,
    items: [
      {
        label: "Catalog",
        href: "/vector-databases/catalog",
        description: "Explore available vector database solutions",
      },
      {
        label: "Instances",
        href: "/vector-databases/endpoints",
        description: "Manage your vector database deployments",
      },
    ],
  },
  {
    label: "Develop",
    icon: <CodeIcon className="mr-2 h-4 w-4" />,
    href: "/develop",
  },
];

export default function Header() {
  const { setTheme } = useTheme();
  const pathname = usePathname();

  const isActive = (href: string) => pathname.startsWith(href);

  return (
    <header className="bg-background border-b">
      <div className="container mx-auto px-4 flex justify-between items-center py-2">
        <div className="flex items-center gap-6">
          <Link
            href="/"
            className="font-bold text-2xl tracking-tight text-primary hover:opacity-80"
          >
            AI Hub
          </Link>
          <NavigationMenu className="hidden md:flex">
            <NavigationMenuList>
              {menuItems.map((item) => (
                <NavigationMenuItem key={item.label}>
                  {item.items ? (
                    <NavigationMenuTrigger
                      className={cn(
                        item.items.some((subItem) => isActive(subItem.href)) &&
                          "font-bold text-primary"
                      )}
                    >
                      {item.icon}
                      {item.label}
                    </NavigationMenuTrigger>
                  ) : (
                    <NavigationMenuLink
                      asChild
                      className={cn(
                        navigationMenuTriggerStyle(),
                        // NavigationMenuLink's base style is a column; keep
                        // icon and label on one line like the triggers.
                        "flex-row",
                        isActive(item.href) && "font-bold text-primary"
                      )}
                    >
                      <Link href={item.href}>
                        {item.icon}
                        {item.label}
                      </Link>
                    </NavigationMenuLink>
                  )}
                  {item.items && (
                    <NavigationMenuContent>
                      <ul className="grid w-[400px] gap-3 p-4 md:w-[500px] md:grid-cols-2 lg:w-[600px]">
                        {item.items.map((subItem) => (
                          <li key={subItem.href}>
                            <NavigationMenuLink asChild>
                              <Link
                                href={subItem.href}
                                className={cn(
                                  "block select-none space-y-1 rounded-md p-3 leading-none no-underline outline-hidden transition-colors hover:bg-accent hover:text-accent-foreground focus:bg-accent focus:text-accent-foreground",
                                  isActive(subItem.href) &&
                                    "bg-accent text-accent-foreground"
                                )}
                              >
                                <div className="text-sm font-medium leading-none">
                                  {subItem.label}
                                </div>
                                <p className="line-clamp-2 text-sm leading-snug text-muted-foreground">
                                  {subItem.description}
                                </p>
                              </Link>
                            </NavigationMenuLink>
                          </li>
                        ))}
                      </ul>
                    </NavigationMenuContent>
                  )}
                </NavigationMenuItem>
              ))}
            </NavigationMenuList>
          </NavigationMenu>
        </div>
        <div className="flex items-center space-x-4">
          <div className="hidden items-center md:flex md:ml-4">
            <ThemeDropdown setTheme={setTheme} />
          </div>
          <div className="flex items-center gap-2 md:hidden">
            <ThemeDropdown setTheme={setTheme} />
            <MobileNav menuItems={menuItems} isActive={isActive} />
          </div>
          {!AUTH_DISABLED && <UserMenu />}
        </div>
      </div>
    </header>
  );
}
