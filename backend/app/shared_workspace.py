"""
共享工作空间（Shared Workspace）
多智能体系统的核心组件，提供智能体间数据共享和状态同步
"""
from __future__ import annotations

import logging
import operator
from dataclasses import dataclass, field
from datetime import datetime
from typing import Annotated, Any, Dict, List, Optional, Sequence
from typing_extensions import TypedDict

logger = logging.getLogger(__name__)


# ==================== 消息传递协议 ====================

@dataclass
class AgentMessage:
    """智能体间消息"""
    from_agent: str  # 发送者智能体ID
    to_agent: str  # 接收者智能体ID（"all" 表示广播）
    message_type: str  # 消息类型：task_request, result, query, update, error
    content: Dict[str, Any]  # 消息内容
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    message_id: str = field(default_factory=lambda: f"msg_{datetime.now().timestamp()}")
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "from_agent": self.from_agent,
            "to_agent": self.to_agent,
            "message_type": self.message_type,
            "content": self.content,
            "timestamp": self.timestamp,
            "message_id": self.message_id,
        }


# ==================== 子任务定义 ====================

@dataclass
class SubTask:
    """子任务定义"""
    task_id: str  # 任务ID
    task_type: str  # 任务类型：retrieval, analysis, summarization, verification
    description: str  # 任务描述
    assigned_agent: Optional[str] = None  # 分配给哪个智能体
    status: str = "pending"  # pending, in_progress, completed, failed
    result: Optional[Dict[str, Any]] = None  # 任务结果
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    error: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "task_id": self.task_id,
            "task_type": self.task_type,
            "description": self.description,
            "assigned_agent": self.assigned_agent,
            "status": self.status,
            "result": self.result,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "error": self.error,
        }


# ==================== 多智能体状态 ====================

class MultiAgentState(TypedDict):
    """
    多智能体共享状态
    扩展自原有的 AgentState，增加多智能体协作所需的字段
    """
    
    # ========== 基础信息（保留原有字段） ==========
    user_query: str  # 用户原始问题
    conversation_history: Annotated[Sequence[Dict[str, str]], operator.add]  # 对话历史
    session_id: Optional[str]  # 会话ID
    user_id: Optional[str]  # 用户ID
    selected_keywords: List[str]
    
    # ========== 单智能体字段（保留兼容性） ==========
    plan: Optional[str]  # 执行计划
    current_step: int  # 当前步骤
    max_iterations: int  # 最大迭代次数
    
    available_tools: List[str]  # 可用工具ID列表
    tool_calls_made: Annotated[List[Dict[str, Any]], operator.add]  # 已执行的工具调用
    tool_results: Annotated[List[Dict[str, Any]], operator.add]  # 工具执行结果
    skipped_tasks: Annotated[List[Dict[str, Any]], operator.add]  # 跳过的任务
    
    use_knowledge_base: bool  # 是否使用知识库
    retrieved_contexts: List[Dict[str, Any]]  # 检索到的上下文
    
    thoughts: Annotated[List[str], operator.add]  # Agent思考过程
    observations: Annotated[List[str], operator.add]  # 观察结果
    
    next_action: Optional[str]  # 下一步动作
    needs_human_input: bool  # 是否需要人工介入
    human_feedback: Optional[str]  # 人工反馈
    
    reflection: Optional[str]  # 反思结果
    quality_score: float  # 质量评分
    
    final_answer: Optional[str]  # 最终答案
    mysql_data: List[Dict[str, Any]]  # MySQL 专家返回的结构化数据
    is_complete: bool  # 是否完成
    error: Optional[str]  # 错误信息
    
    # ========== 多智能体专用字段（新增） ==========
    
    # 协调信息
    orchestrator_plan: Optional[str]  # 协调器的任务分解计划
    sub_tasks: List[Dict[str, Any]]  # 子任务列表（SubTask 序列化）
    current_subtask_index: int  # 当前执行的子任务索引
    
    # 智能体管理
    active_agents: List[str]  # 当前活跃的智能体ID列表
    agent_results: Dict[str, Dict[str, Any]]  # 各智能体的执行结果 {agent_id: result}
    agent_status: Dict[str, str]  # 各智能体的状态 {agent_id: status}
    
    # 消息通信
    messages: Annotated[List[Dict[str, Any]], operator.add]  # 智能体间消息（AgentMessage序列化）
    
    # 共享数据
    shared_data: Dict[str, Any]  # 智能体间共享的数据（如检索结果、分析数据等）
    
    # 执行模式
    execution_mode: str  # 执行模式：sequential（串行）或 parallel（并行）
    
    # 多智能体特定的思考和观察
    agent_thoughts: Dict[str, List[str]]  # 各智能体的思考 {agent_id: [thought1, ...]}
    agent_observations: Dict[str, List[str]]  # 各智能体的观察 {agent_id: [obs1, ...]}


# ==================== 工作空间管理器 ====================

class SharedWorkspace:
    """
    共享工作空间管理器
    提供智能体间数据共享、消息传递、状态同步等功能
    """
    
    def __init__(self, state: MultiAgentState):
        self.state = state
    
    # ========== 消息管理 ==========
    
    def send_message(
        self,
        from_agent: str,
        to_agent: str,
        message_type: str,
        content: Dict[str, Any],
    ) -> None:
        """
        发送消息
        
        Args:
            from_agent: 发送者智能体ID
            to_agent: 接收者智能体ID（"all" 表示广播）
            message_type: 消息类型
            content: 消息内容
        """
        message = AgentMessage(
            from_agent=from_agent,
            to_agent=to_agent,
            message_type=message_type,
            content=content,
        )
        
        # 添加到消息列表
        if "messages" not in self.state:
            self.state["messages"] = []
        
        self.state["messages"].append(message.to_dict())
        
        logger.debug(
            f"📨 消息发送: {from_agent} -> {to_agent} "
            f"[{message_type}]: {str(content)[:100]}"
        )
    
    def get_messages_for_agent(
        self,
        agent_id: str,
        message_type: Optional[str] = None,
    ) -> List[AgentMessage]:
        """
        获取发给特定智能体的消息
        
        Args:
            agent_id: 智能体ID
            message_type: 消息类型过滤（可选）
        
        Returns:
            消息列表
        """
        messages = []
        
        for msg_dict in self.state.get("messages", []):
            # 检查是否是发给该智能体或广播消息
            if msg_dict["to_agent"] in [agent_id, "all"]:
                # 如果指定了消息类型，进行过滤
                if message_type is None or msg_dict["message_type"] == message_type:
                    messages.append(AgentMessage(**msg_dict))
        
        return messages
    
    def get_latest_message_from(
        self,
        from_agent: str,
        message_type: Optional[str] = None,
    ) -> Optional[AgentMessage]:
        """
        获取来自特定智能体的最新消息
        
        Args:
            from_agent: 发送者智能体ID
            message_type: 消息类型过滤（可选）
        
        Returns:
            最新消息或 None
        """
        messages = []
        
        for msg_dict in reversed(self.state.get("messages", [])):
            if msg_dict["from_agent"] == from_agent:
                if message_type is None or msg_dict["message_type"] == message_type:
                    return AgentMessage(**msg_dict)
        
        return None
    
    # ========== 子任务管理 ==========
    
    def add_subtask(self, subtask: SubTask) -> None:
        """添加子任务"""
        if "sub_tasks" not in self.state:
            self.state["sub_tasks"] = []
        
        self.state["sub_tasks"].append(subtask.to_dict())
        
        logger.info(
            f"📝 添加子任务: {subtask.task_id} "
            f"[{subtask.task_type}] - {subtask.description}"
        )
    
    def get_subtask(self, task_id: str) -> Optional[SubTask]:
        """获取子任务"""
        for task_dict in self.state.get("sub_tasks", []):
            if task_dict["task_id"] == task_id:
                return SubTask(**task_dict)
        return None
    
    def update_subtask_status(
        self,
        task_id: str,
        status: str,
        result: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
    ) -> None:
        """
        更新子任务状态
        
        Args:
            task_id: 任务ID
            status: 新状态
            result: 任务结果（可选）
            error: 错误信息（可选）
        """
        for task_dict in self.state.get("sub_tasks", []):
            if task_dict["task_id"] == task_id:
                task_dict["status"] = status
                
                if status == "in_progress" and not task_dict.get("started_at"):
                    task_dict["started_at"] = datetime.now().isoformat()
                
                if status in ["completed", "failed"]:
                    task_dict["completed_at"] = datetime.now().isoformat()
                
                if result is not None:
                    task_dict["result"] = result
                
                if error is not None:
                    task_dict["error"] = error
                
                logger.info(f"✅ 更新子任务状态: {task_id} -> {status}")
                break
    
    def get_pending_subtasks(self) -> List[SubTask]:
        """获取待执行的子任务"""
        return [
            SubTask(**task_dict)
            for task_dict in self.state.get("sub_tasks", [])
            if task_dict["status"] == "pending"
        ]
    
    def get_completed_subtasks(self) -> List[SubTask]:
        """获取已完成的子任务"""
        return [
            SubTask(**task_dict)
            for task_dict in self.state.get("sub_tasks", [])
            if task_dict["status"] == "completed"
        ]
    
    def all_subtasks_completed(self) -> bool:
        """检查是否所有子任务都已完成"""
        sub_tasks = self.state.get("sub_tasks", [])
        if not sub_tasks:
            return False
        
        return all(
            task["status"] in ["completed", "failed"]
            for task in sub_tasks
        )
    
    # ========== 智能体管理 ==========
    
    def register_agent(self, agent_id: str) -> None:
        """注册智能体"""
        if "active_agents" not in self.state:
            self.state["active_agents"] = []
        
        if agent_id not in self.state["active_agents"]:
            self.state["active_agents"].append(agent_id)
            logger.info(f"🤖 注册智能体: {agent_id}")
    
    def update_agent_status(self, agent_id: str, status: str) -> None:
        """更新智能体状态"""
        if "agent_status" not in self.state:
            self.state["agent_status"] = {}
        
        self.state["agent_status"][agent_id] = status
        logger.debug(f"🔄 智能体状态更新: {agent_id} -> {status}")
    
    def store_agent_result(
        self,
        agent_id: str,
        result: Dict[str, Any],
    ) -> None:
        """存储智能体的执行结果"""
        if "agent_results" not in self.state:
            self.state["agent_results"] = {}
        
        self.state["agent_results"][agent_id] = result
        logger.info(f"💾 存储智能体结果: {agent_id}")
    
    def get_agent_result(self, agent_id: str) -> Optional[Dict[str, Any]]:
        """获取智能体的执行结果"""
        return self.state.get("agent_results", {}).get(agent_id)
    
    def add_agent_thought(self, agent_id: str, thought: str) -> None:
        """添加智能体的思考"""
        if "agent_thoughts" not in self.state:
            self.state["agent_thoughts"] = {}
        
        if agent_id not in self.state["agent_thoughts"]:
            self.state["agent_thoughts"][agent_id] = []
        
        self.state["agent_thoughts"][agent_id].append(thought)
    
    def add_agent_observation(self, agent_id: str, observation: str) -> None:
        """添加智能体的观察"""
        if "agent_observations" not in self.state:
            self.state["agent_observations"] = {}
        
        if agent_id not in self.state["agent_observations"]:
            self.state["agent_observations"][agent_id] = []
        
        self.state["agent_observations"][agent_id].append(observation)
    
    # ========== 共享数据管理 ==========
    
    def set_shared_data(self, key: str, value: Any) -> None:
        """设置共享数据"""
        if "shared_data" not in self.state:
            self.state["shared_data"] = {}
        
        self.state["shared_data"][key] = value
        logger.debug(f"💾 设置共享数据: {key}")
    
    def get_shared_data(self, key: str, default: Any = None) -> Any:
        """获取共享数据"""
        return self.state.get("shared_data", {}).get(key, default)
    
    def update_shared_data(self, updates: Dict[str, Any]) -> None:
        """批量更新共享数据"""
        if "shared_data" not in self.state:
            self.state["shared_data"] = {}
        
        self.state["shared_data"].update(updates)
        logger.debug(f"💾 批量更新共享数据: {list(updates.keys())}")
    
    def get_current_subtask(self) -> Optional[SubTask]:
        """获取当前正在执行的子任务"""
        subtasks = self.state.get("subtasks", [])
        for task_dict in subtasks:
            if task_dict.get("status") == "in_progress":
                return SubTask(
                    task_id=task_dict.get("task_id", ""),
                    task_type=task_dict.get("task_type", ""),
                    description=task_dict.get("description", ""),
                    assigned_agent=task_dict.get("assigned_agent", ""),
                )
        return None
    
    # ========== 工作空间摘要 ==========
    
    def get_workspace_summary(self) -> str:
        """获取工作空间摘要（用于日志或调试）"""
        sub_tasks = self.state.get("sub_tasks", [])
        active_agents = self.state.get("active_agents", [])
        messages_count = len(self.state.get("messages", []))
        
        completed_tasks = sum(1 for t in sub_tasks if t["status"] == "completed")
        total_tasks = len(sub_tasks)
        
        summary = f"""
工作空间状态摘要:
- 活跃智能体: {len(active_agents)} ({', '.join(active_agents)})
- 子任务进度: {completed_tasks}/{total_tasks}
- 消息数量: {messages_count}
- 执行模式: {self.state.get('execution_mode', 'sequential')}
"""
        return summary.strip()


# ==================== 初始化函数 ====================

def create_initial_multi_agent_state(
    user_query: str,
    conversation_history: Optional[List[Dict[str, str]]] = None,
    session_id: Optional[str] = None,
    user_id: Optional[str] = None,
    use_knowledge_base: bool = False,
    available_tools: Optional[List[str]] = None,
    execution_mode: str = "sequential",
    selected_keywords: Optional[List[str]] = None,
) -> MultiAgentState:
    """
    创建初始的多智能体状态
    
    Args:
        user_query: 用户查询
        conversation_history: 对话历史
        session_id: 会话ID
        user_id: 用户ID
        use_knowledge_base: 是否使用知识库
        available_tools: 可用工具列表
        execution_mode: 执行模式（sequential 或 parallel）
    
    Returns:
        初始化的多智能体状态
    """
    return MultiAgentState(
        # 基础信息
        user_query=user_query,
        conversation_history=conversation_history or [],
        session_id=session_id,
        user_id=user_id,
        selected_keywords=selected_keywords or [],
        # 单智能体字段（兼容性）
        plan=None,
        current_step=0,
        max_iterations=20,
        
        available_tools=available_tools or [],
        tool_calls_made=[],
        tool_results=[],
        skipped_tasks=[],
        
        use_knowledge_base=use_knowledge_base,
        retrieved_contexts=[],
        
        thoughts=[],
        observations=[],
        
        next_action=None,
        needs_human_input=False,
        human_feedback=None,
        
        reflection=None,
        quality_score=0.0,
        
        final_answer=None,
        mysql_data=[],
        is_complete=False,
        error=None,
        
        # 多智能体字段
        orchestrator_plan=None,
        sub_tasks=[],
        current_subtask_index=0,
        
        active_agents=[],
        agent_results={},
        agent_status={},
        
        messages=[],
        
        shared_data={},
        
        execution_mode=execution_mode,
        
        agent_thoughts={},
        agent_observations={},
    )
