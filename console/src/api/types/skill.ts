export interface SkillSpec {
  name: string;
  description?: string;
  content: string;
  source: string;
  path: string;
  enabled?: boolean;
  channels?: string[];
  sync_to_pool?: {
    status?: string;
    pool_name?: string;
  };
  config?: Record<string, unknown>;
}

export interface PoolSkillSpec {
  name: string;
  description?: string;
  content: string;
  source: string;
  path: string;
  protected: boolean;
  version_text?: string;
  commit_text?: string;
  config?: Record<string, unknown>;
}

export interface WorkspaceSkillSummary {
  agent_id: string;
  workspace_dir: string;
  skills: SkillSpec[];
}

export interface HubSkillSpec {
  slug: string;
  name: string;
  description?: string;
  version?: string;
  source_url?: string;
}

// Legacy Skill interface for backward compatibility
export interface Skill {
  id: string;
  name: string;
  description: string;
  function_name: string;
  enabled: boolean;
  version: string;
  tags: string[];
  created_at: number;
  updated_at: number;
}
