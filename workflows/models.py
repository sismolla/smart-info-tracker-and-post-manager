from django.db import models
from connectors.models import InformationSource
from intelligence.models import CollectedItem

class Workflow(models.Model):
    """
    Configurable automated processing pipeline per source or category.
    """
    name = models.CharField(max_length=150)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    
    # Conditional triggers
    source = models.ForeignKey(InformationSource, null=True, blank=True, on_delete=models.SET_NULL, related_name='workflows')
    auto_approve = models.BooleanField(default=False, help_text="Automatically approve items matching criteria without manual review")
    auto_approve_min_score = models.PositiveSmallIntegerField(default=80, help_text="Minimum relevance score for auto-approval")
    auto_publish = models.BooleanField(default=False, help_text="Publish immediately upon approval")
    
    config = models.JSONField(default=dict, blank=True, help_text="Pipeline step configuration and routing rules")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name


class WorkflowExecution(models.Model):
    """
    Tracks state transitions of an item as it traverses the workflow.
    """
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('in_progress', 'In Progress'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
    ]

    workflow = models.ForeignKey(Workflow, on_delete=models.CASCADE, related_name='executions')
    item = models.ForeignKey(CollectedItem, on_delete=models.CASCADE, related_name='workflow_executions')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    current_step = models.CharField(max_length=80, default='ingestion')
    execution_log = models.JSONField(default=list, blank=True)
    error_message = models.TextField(blank=True)
    started_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"Workflow #{self.workflow.id} on Item #{self.item.id} ({self.status})"
