export interface Notebook {
  id: string;
  name: string;
  type: string;
  framework: string;
  nvidia_gpu: boolean;
  image: string;
  resources_cpu: string;
  resources_memory: string;
  resources_gpu: string;
  storage_size: string;
  service_type: string;
  service_port: number;
  created_at: string;
  updated_at: string;
  status: string;
  ready: boolean;
  endpoint: string;
}