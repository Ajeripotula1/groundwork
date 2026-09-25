import { Card, CardHeader, CardTitle, CardContent, CardDescription } from '../ui/card'
import { Badge } from '../ui/badge'
import { Button } from '../ui/button'
import { ExternalLink } from 'lucide-react'

// Generic "card with a title" wrapper - one per top-level ExtractedProfile
// field (contact/summary/education/...). See the earlier discussion: this
// only standardizes the outer chrome, the inside is bespoke per field.
const Section = ({ title, children }) => (
  <Card>
    <CardHeader>
      <CardTitle>{title}</CardTitle>
    </CardHeader>
    <CardContent className="space-y-1">{children}</CardContent>
  </Card>
)

// One label/value row, e.g. "Email: someone@example.com". Centralizes the
// null/undefined fallback so every field in Contact doesn't repeat its own
// `?? '—'` check - a missing value renders as a muted em dash instead of
// the literal text "null" or a blank line.
const Field = ({ label, value }) => (
  <CardDescription>
    <span className="font-semibold">{label}: </span>
    {value || <span className="text-muted-foreground">—</span>}
  </CardDescription>
)

// Shown in place of a list section's items when that list is empty (e.g. a
// resume with no Certifications section - a legitimate state per
// schema.py's design rule, not an error). Plain empty-list check, not a
// null check: every array field defaults to [] server-side, never null.
const EmptyNote = ({ children }) => (
  <p className="text-sm text-muted-foreground">{children}</p>
)

const EducationEntry = ({ entry }) => (
  <div className="space-y-1">
    <p className="font-medium">{entry.institution}</p>
    <p className="text-sm text-muted-foreground">
      {[entry.degree, entry.location, entry.dates].filter(Boolean).join(' · ')}
    </p>
    {entry.details.length > 0 && (
      <ul className="list-disc pl-5 text-sm">
        {entry.details.map((detail, i) => (
          <li key={i}>{detail}</li>
        ))}
      </ul>
    )}
  </div>
)

const ExperienceEntry = ({ entry }) => (
  <div className="space-y-1">
    <p className="font-medium">
      {entry.title} · {entry.company}
    </p>
    <p className="text-sm text-muted-foreground">
      {[entry.location, entry.dates].filter(Boolean).join(' · ')}
    </p>
    {entry.bullets.length > 0 && (
      <ul className="list-disc pl-5 text-sm">
        {entry.bullets.map((bullet, i) => (
          <li key={i}>{bullet}</li>
        ))}
      </ul>
    )}
  </div>
)

const ProjectEntry = ({ entry }) => (
  <div className="space-y-1">
    <div className="flex items-center justify-between gap-2">
      <p className="font-medium">{entry.name}</p>
      {entry.url && (
        <Button variant="link" size="sm" render={<a href={entry.url} target="_blank" rel="noreferrer" />}>
          View
          <ExternalLink />
        </Button>
      )}
    </div>
    {entry.dates && <p className="text-sm text-muted-foreground">{entry.dates}</p>}
    {entry.bullets.length > 0 && (
      <ul className="list-disc pl-5 text-sm">
        {entry.bullets.map((bullet, i) => (
          <li key={i}>{bullet}</li>
        ))}
      </ul>
    )}
    {entry.technologies.length > 0 && (
      <div className="flex flex-wrap gap-1 pt-1">
        {entry.technologies.map((tech) => (
          <Badge key={tech} variant="outline">
            {tech}
          </Badge>
        ))}
      </div>
    )}
  </div>
)

const CertificationEntry = ({ entry }) => (
  <div>
    <p className="font-medium">{entry.name}</p>
    <p className="text-sm text-muted-foreground">
      {[entry.issuer, entry.date].filter(Boolean).join(' · ')}
    </p>
  </div>
)

export const ProfileView = ({ profile }) => {
  // Defensive on two levels: `useProfile()` resolves to `data: null` for a
  // user with no profile yet (see useProfile.js), so a caller that forgets
  // to guard before rendering this component would otherwise crash on the
  // destructure below - bail out to nothing rather than throw. The `?? {}`
  // plus per-field defaults on top of that guard against any individual
  // field being missing on a partial/malformed payload, even though the
  // backend schema (schema.py) guarantees every field defaults to a real
  // value (never a bare `null` for the object/array fields), never undefined.
  if (!profile) return null

  const {
    contact = {},
    summary = null,
    education = [],
    experience = [],
    projects = [],
    certifications = [],
    skills = [],
  } = profile

  return (
    <div className="space-y-4">
      <Section title="Contact">
        <Field label="Name" value={contact.name} />
        <Field label="Email" value={contact.email} />
        <Field label="Phone" value={contact.phone} />
        <Field label="Location" value={contact.location} />
        <Field label="Links" value={contact.links?.length ? contact.links.join(', ') : null} />
      </Section>

      <Section title="Summary">
        {summary || <EmptyNote>No summary on this resume.</EmptyNote>}
      </Section>

      <Section title="Education">
        {education.length > 0 ? (
          <div className="space-y-4">
            {education.map((entry, i) => (
              <EducationEntry key={i} entry={entry} />
            ))}
          </div>
        ) : (
          <EmptyNote>No education listed.</EmptyNote>
        )}
      </Section>

      <Section title="Experience">
        {experience.length > 0 ? (
          <div className="space-y-4">
            {experience.map((entry, i) => (
              <ExperienceEntry key={i} entry={entry} />
            ))}
          </div>
        ) : (
          <EmptyNote>No work experience listed.</EmptyNote>
        )}
      </Section>

      <Section title="Projects">
        {projects.length > 0 ? (
          <div className="space-y-4">
            {projects.map((entry, i) => (
              <ProjectEntry key={i} entry={entry} />
            ))}
          </div>
        ) : (
          <EmptyNote>No projects listed.</EmptyNote>
        )}
      </Section>

      <Section title="Certifications">
        {certifications.length > 0 ? (
          <div className="space-y-3">
            {certifications.map((entry, i) => (
              <CertificationEntry key={i} entry={entry} />
            ))}
          </div>
        ) : (
          <EmptyNote>No certifications listed.</EmptyNote>
        )}
      </Section>

      <Section title="Skills">
        {skills.length > 0 ? (
          <div className="flex flex-wrap gap-1">
            {skills.map((skill) => (
              <Badge key={skill} variant="secondary">
                {skill}
              </Badge>
            ))}
          </div>
        ) : (
          <EmptyNote>No skills listed.</EmptyNote>
        )}
      </Section>
    </div>
  )
}
