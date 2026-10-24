import { Component, type ErrorInfo, type ReactNode } from 'react';
import { EmptyPanel, PanelFrame } from './panelPrimitives';

export interface PanelErrorBoundaryProps {
  name: string;
  children: ReactNode;
  className?: string;
  resetKey?: string | number;
  onError?: (error: Error, info: ErrorInfo) => void;
}

interface PanelErrorBoundaryState { failed: boolean }

export class PanelErrorBoundary extends Component<PanelErrorBoundaryProps, PanelErrorBoundaryState> {
  state: PanelErrorBoundaryState = { failed: false };

  static getDerivedStateFromError(): PanelErrorBoundaryState {
    return { failed: true };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    this.props.onError?.(error, info);
  }

  componentDidUpdate(previousProps: PanelErrorBoundaryProps) {
    if (this.state.failed && previousProps.resetKey !== this.props.resetKey) {
      this.setState({ failed: false });
    }
  }

  render() {
    if (!this.state.failed) return this.props.children;
    return (
      <PanelFrame title={this.props.name} eyebrow="Degraded" className={this.props.className}>
        <EmptyPanel label="This panel could not render" detail="The rest of the dashboard is still running. New data will retry the panel." />
      </PanelFrame>
    );
  }
}
