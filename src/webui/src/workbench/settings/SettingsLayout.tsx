import { ReactNode } from 'react'
export function SettingsBlock({title,description,children,action}:{title:string;description?:string;children:ReactNode;action?:ReactNode}) {
  return <section className="wb-settings-block" aria-label={title}><header><div><h3>{title}</h3>{description&&<p>{description}</p>}</div>{action}</header><div className="wb-settings-block-body">{children}</div></section>
}
export function SettingsActions({children,status}:{children:ReactNode;status:string}) {
  return <footer className="wb-settings-actions"><span role="status">{status}</span><div>{children}</div></footer>
}
